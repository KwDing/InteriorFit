#include "InteriorFitAreaSurfaceSampler.h"

#include "InteriorFitEditorWorld.h"

#include "InteriorFitArea.h"

#include "Components/InstancedStaticMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "StaticMeshResources.h"
#include "InteriorFitSurfaceSampleJSON.h"
#include "CollisionQueryParams.h"

#define LOCTEXT_NAMESPACE "InteriorFitAreaSurfaceSampler"

namespace
{
    // Raster cells and fallback collision tests share a work counter.
    constexpr int64 MaxSampleWork = 8000000;
    constexpr int32 MaxIndicesPerMesh = 1500000;
    constexpr int32 MaxInstancesPerComponent = 1024;
    constexpr int64 MaxSampleTriangles = 500000;
    constexpr int32 MaxSourceActors = 128;
    constexpr int32 MaxSourceComponents = 512;
    constexpr double GridCoarseningFactor = 1.25;
    constexpr double MaxCoarseningStepCm = 1000000;
    constexpr float MinimumRequestedCellCm = 25;

    // Ignore nearly degenerate XY projections and allow barycentric roundoff.
    constexpr double MinDoubleProjectedAreaCm2 = 0.01;
    constexpr double MinBarycentricWeight = -0.00001;
    constexpr double MaxBarycentricSum = 1.00001;
    // Cover rays start above the selection and end short of the sampled surface.
    constexpr double CoverProbeAboveBoundsCm = 10000;
    constexpr double CoverProbeEndAboveSurfaceCm = 5;
    constexpr double CollisionProbeBoundsPaddingCm = 100;

    struct FAreaGrid
    {
        FVector Origin;
        double Step;
        int32 Width;
        int32 Height;
        TArray<double> Heights;
        int64 Work = 0;
        int64 Triangles = 0;
        bool Rasterize(const FVector& A, const FVector& B, const FVector& C)
        {
            const double Denom = (B.Y - C.Y) * (A.X - C.X) + (C.X - B.X) * (A.Y - C.Y);
            if (FMath::Abs(Denom) < MinDoubleProjectedAreaCm2)
            {
                return true;
            }
            const int32 Left = FMath::Clamp(
                FMath::FloorToInt((FMath::Min3(A.X, B.X, C.X) - Origin.X) / Step), 0, Width - 1);
            const int32 Right = FMath::Clamp(
                FMath::FloorToInt((FMath::Max3(A.X, B.X, C.X) - Origin.X) / Step), 0, Width - 1);
            const int32 Bottom = FMath::Clamp(
                FMath::FloorToInt((FMath::Min3(A.Y, B.Y, C.Y) - Origin.Y) / Step), 0, Height - 1);
            const int32 Top = FMath::Clamp(
                FMath::FloorToInt((FMath::Max3(A.Y, B.Y, C.Y) - Origin.Y) / Step), 0, Height - 1);
            Work += static_cast<int64>(Right - Left + 1) * (Top - Bottom + 1);
            if (Work > MaxSampleWork)
            {
                return false;
            }
            for (int32 Y = Bottom; Y <= Top; ++Y)
            {
                for (int32 X = Left; X <= Right; ++X)
                {
                    const double PX = Origin.X + (X + 0.5) * Step, PY = Origin.Y + (Y + 0.5) * Step;
                    const double U = ((B.Y - C.Y) * (PX - C.X) + (C.X - B.X) * (PY - C.Y)) / Denom;
                    const double V = ((C.Y - A.Y) * (PX - C.X) + (A.X - C.X) * (PY - C.Y)) / Denom;
                    if (U < MinBarycentricWeight || V < MinBarycentricWeight ||
                        U + V > MaxBarycentricSum)
                    {
                        continue;
                    }
                    Heights[Y * Width + X] =
                        FMath::Max(Heights[Y * Width + X], U * A.Z + V * B.Z + (1 - U - V) * C.Z);
                }
            }
            return true;
        }
    };
    bool RasterMesh(UStaticMeshComponent* Component, FAreaGrid& Grid)
    {
        UStaticMesh* Mesh = Component->GetStaticMesh();
        if (!Mesh || !Mesh->GetRenderData() || Mesh->GetRenderData()->LODResources.IsEmpty())
        {
            return false;
        }
        const FStaticMeshLODResources& LOD = Mesh->GetRenderData()->LODResources[0];
        const FIndexArrayView Indices = LOD.IndexBuffer.GetArrayView();
        if (Indices.Num() > MaxIndicesPerMesh)
        {
            return false;
        }
        UInstancedStaticMeshComponent* Instances = Cast<UInstancedStaticMeshComponent>(Component);
        const int32 Count = Instances ? Instances->GetInstanceCount() : 1;
        if (Count > MaxInstancesPerComponent)
        {
            return false;
        }
        for (int32 Instance = 0; Instance < Count; ++Instance)
        {
            FTransform Transform = Component->GetComponentTransform();
            if (Instances && !Instances->GetInstanceTransform(Instance, Transform, true))
            {
                return false;
            }
            for (int32 Index = 0; Index + 2 < Indices.Num(); Index += 3)
            {
                if (++Grid.Triangles > MaxSampleTriangles)
                {
                    return false;
                }
                FVector Points[3];
                for (int32 Corner = 0; Corner < 3; ++Corner)
                {
                    Points[Corner] = Transform.TransformPosition(
                        FVector(LOD.VertexBuffers.PositionVertexBuffer.VertexPosition(
                            Indices[Index + Corner])));
                }
                if (!Grid.Rasterize(Points[0], Points[1], Points[2]))
                {
                    return false;
                }
            }
        }
        return true;
    }
} // namespace
namespace
{
    FString EncodeExposedCells(UWorld* World, const FBox& Bounds,
                               const FCollisionQueryParams& Query, const FAreaGrid& Grid,
                               bool bExcludeCoveredSurface)
    {
        TArray<TSharedPtr<FJsonValue>> Cells;
        for (int32 Y = 0; Y < Grid.Height; ++Y)
        {
            for (int32 X = 0; X < Grid.Width; ++X)
            {
                const double Z = Grid.Heights[Y * Grid.Width + X];
                if (Z == -TNumericLimits<double>::Max())
                {
                    continue;
                }
                const FVector Point(Grid.Origin.X + (X + 0.5) * Grid.Step,
                                    Grid.Origin.Y + (Y + 0.5) * Grid.Step, Z);
                FHitResult Cover;
                if (bExcludeCoveredSurface &&
                    World->LineTraceSingleByChannel(
                        Cover, FVector(Point.X, Point.Y, Bounds.Max.Z + CoverProbeAboveBoundsCm),
                        Point + FVector(0, 0, CoverProbeEndAboveSurfaceCm), ECC_Visibility, Query))
                {
                    continue;
                }
                Cells.Add(MakeShared<FJsonValueArray>(
                    InteriorFitSurfaceSampleJSON::VectorJSON(Point - Grid.Origin)));
            }
        }
        if (Cells.IsEmpty())
        {
            return InteriorFitSurfaceSampleJSON::Fail(
                LOCTEXT("NoExposedCells", "没有可用的裸露地表格。请检查几何体和碰撞，或在 Area "
                                          "设置中关闭 exclude_covered。")
                    .ToString());
        }
        TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
        Data->SetArrayField(TEXT("origin"), InteriorFitSurfaceSampleJSON::VectorJSON(Grid.Origin));
        Data->SetArrayField(TEXT("cells"), Cells);
        Data->SetNumberField(TEXT("cell_size"), Grid.Step);
        Data->SetNumberField(TEXT("sample_work"), Grid.Work);
        return InteriorFitSurfaceSampleJSON::Encode(Data);
    }

    bool TraceComponentCells(UPrimitiveComponent* Component, const FBox& Bounds,
                             const FCollisionQueryParams& Query, FAreaGrid& Grid)
    {
        for (int32 Y = 0; Y < Grid.Height; ++Y)
        {
            for (int32 X = 0; X < Grid.Width; ++X)
            {
                if (++Grid.Work > MaxSampleWork)
                {
                    return false;
                }
                const FVector Start(Grid.Origin.X + (X + 0.5) * Grid.Step,
                                    Grid.Origin.Y + (Y + 0.5) * Grid.Step,
                                    Bounds.Max.Z + CollisionProbeBoundsPaddingCm);
                FHitResult Hit;
                if (Component->LineTraceComponent(
                        Hit, Start,
                        FVector(Start.X, Start.Y, Bounds.Min.Z - CollisionProbeBoundsPaddingCm),
                        Query))
                {
                    Grid.Heights[Y * Grid.Width + X] =
                        FMath::Max(Grid.Heights[Y * Grid.Width + X], Hit.ImpactPoint.Z);
                }
            }
        }
        return true;
    }

    // Prefer source triangles. Components without a static mesh use bounded vertical traces.
    FString SampleComponents(const TArray<UPrimitiveComponent*>& Components, const FBox& Bounds,
                             const FCollisionQueryParams& Query, FAreaGrid& Grid)
    {
        for (UPrimitiveComponent* Component : Components)
        {
            if (UStaticMeshComponent* Mesh = Cast<UStaticMeshComponent>(Component))
            {
                if (!RasterMesh(Mesh, Grid))
                {
                    return InteriorFitSurfaceSampleJSON::Fail(
                        LOCTEXT("RasterBudget", "无法读取网格渲染几何体，或已超出采样预算。请减少 "
                                                "Actor 数量或增大格宽。")
                            .ToString());
                }
                continue;
            }
            if (!TraceComponentCells(Component, Bounds, Query, Grid))
            {
                return InteriorFitSurfaceSampleJSON::Fail(
                    LOCTEXT("TraceBudget", "已超出地表射线采样预算。").ToString());
            }
        }
        return {};
    }
} // namespace

FString InteriorFitAreaSurfaceSampler::SampleAreaSurface(const TArray<AActor*>& Sources,
                                                         float RequestedCellSize,
                                                         bool bExcludeCoveredSurface)
{
    const bool bValidSources = !Sources.IsEmpty() && Sources.Num() <= MaxSourceActors;
    const bool bValidSize =
        FMath::IsFinite(RequestedCellSize) && RequestedCellSize >= MinimumRequestedCellCm;
    if (!IsInGameThread() || !bValidSources || !bValidSize)
    {
        return InteriorFitSurfaceSampleJSON::Fail(
            LOCTEXT("InvalidInput", "请选择地表 Actor，格宽至少为 25 cm。").ToString());
    }
    UWorld* World = IsValid(Sources[0]) ? Sources[0]->GetWorld() : nullptr;
    if (!InteriorFitEditorWorld::IsEditorWorld(World))
    {
        return InteriorFitSurfaceSampleJSON::Fail(
            LOCTEXT("EditorWorld", "请在编辑器世界中执行。").ToString());
    }
    FBox Bounds(ForceInit);
    TArray<UPrimitiveComponent*> Components;
    FCollisionQueryParams Query(SCENE_QUERY_STAT(InteriorFitArea), true);
    for (AActor* Actor : Sources)
    {
        if (!IsValid(Actor) || Actor->GetWorld() != World)
        {
            return InteriorFitSurfaceSampleJSON::Fail(
                LOCTEXT("InvalidActor", "来源 Actor 无效。").ToString());
        }
        Query.AddIgnoredActor(Actor);
        TInlineComponentArray<UPrimitiveComponent*> Owned;
        Actor->GetComponents(Owned);
        for (UPrimitiveComponent* Component : Owned)
        {
            if (!IsValid(Component) || !Component->IsRegistered() || Component->IsEditorOnly())
            {
                continue;
            }
            Components.Add(Component);
            Bounds += Component->Bounds.GetBox();
        }
    }
    if (!Bounds.IsValid || Components.IsEmpty() || Components.Num() > MaxSourceComponents)
    {
        return InteriorFitSurfaceSampleJSON::Fail(
            LOCTEXT("InvalidComponents", "没有可采样的地表组件，或组件数量超出上限。").ToString());
    }
    FAreaGrid Grid;
    Grid.Origin = Bounds.Min;
    Grid.Step = RequestedCellSize;
    do
    {
        Grid.Width = FMath::Max(1, FMath::CeilToInt(Bounds.GetSize().X / Grid.Step));
        Grid.Height = FMath::Max(1, FMath::CeilToInt(Bounds.GetSize().Y / Grid.Step));
        if (static_cast<int64>(Grid.Width) * Grid.Height <= AInteriorFitArea::MaxSurfaceCells)
        {
            break;
        }
        Grid.Step *= GridCoarseningFactor;
    } while (Grid.Step < MaxCoarseningStepCm);
    if (static_cast<int64>(Grid.Width) * Grid.Height > AInteriorFitArea::MaxSurfaceCells)
    {
        return InteriorFitSurfaceSampleJSON::Fail(
            LOCTEXT("SurfaceTooLarge", "地表范围过大。").ToString());
    }
    Grid.Heights.Init(-TNumericLimits<double>::Max(), Grid.Width * Grid.Height);
    const FString SampleError = SampleComponents(Components, Bounds, Query, Grid);
    if (!SampleError.IsEmpty())
    {
        return SampleError;
    }
    return EncodeExposedCells(World, Bounds, Query, Grid, bExcludeCoveredSurface);
}

#undef LOCTEXT_NAMESPACE
