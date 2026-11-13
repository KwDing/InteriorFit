#include "InteriorFitSplineBoundaryExtractor.h"

#include "InteriorFitEditorWorld.h"

#include "Components/InstancedStaticMeshComponent.h"
#include "Components/StaticMeshComponent.h"
#include "Engine/StaticMesh.h"
#include "Engine/World.h"
#include "GameFramework/Actor.h"
#include "StaticMeshResources.h"
#include "InteriorFitSurfaceSampleJSON.h"

#define LOCTEXT_NAMESPACE "InteriorFitSplineBoundaryExtractor"

namespace
{
    // Cap render mesh traversal and the boundary payload consumed by Python.
    constexpr int32 MaxSourceInstances = 1024;
    constexpr int32 MaxExpandedMeshIndices = 1500000;
    constexpr int32 MaxSourceTriangles = 500000;
    constexpr int32 MaxBoundarySourceActors = 128;
    constexpr int32 MaxBoundaryEdges = 8192;
    constexpr int32 BoundaryWeldGridStepsPerCm = 100;
    // This coordinate guard keeps the quantized key within the int32 range.
    constexpr double MaxWeldCoordinateCm = 10000000;
    constexpr double HorizontalPlaneToleranceCm = 1;

    // Weld render-vertex seams at 0.01 cm; retain the original, unquantized position.
    struct FPlanarSurfaceBoundary
    {
        TMap<FIntVector, int32> VertexIDs;
        TArray<FVector> Positions;
        TMap<FIntPoint, int32> EdgeUses;
        int32 TriangleCount = 0;

        int32 AddVertex(const FVector& Position)
        {
            const FIntVector Key(FMath::RoundToInt(Position.X * BoundaryWeldGridStepsPerCm),
                                 FMath::RoundToInt(Position.Y * BoundaryWeldGridStepsPerCm),
                                 FMath::RoundToInt(Position.Z * BoundaryWeldGridStepsPerCm));
            if (const int32* Existing = VertexIDs.Find(Key))
            {
                return *Existing;
            }
            const int32 ID = Positions.Add(Position);
            VertexIDs.Add(Key, ID);
            return ID;
        }

        bool AddTriangle(const FStaticMeshLODResources& LOD, const FIndexArrayView& Indices,
                         int32 Index, const FTransform& Transform)
        {
            if (++TriangleCount > MaxSourceTriangles)
            {
                return false;
            }
            int32 IDs[3];
            for (int32 Corner = 0; Corner < 3; ++Corner)
            {
                const FVector Position = Transform.TransformPosition(
                    FVector(LOD.VertexBuffers.PositionVertexBuffer.VertexPosition(
                        Indices[Index + Corner])));
                if (Position.ContainsNaN() || Position.GetAbsMax() > MaxWeldCoordinateCm)
                {
                    return false;
                }
                if (!Positions.IsEmpty() &&
                    FMath::Abs(Position.Z - Positions[0].Z) > HorizontalPlaneToleranceCm)
                {
                    return false;
                }
                IDs[Corner] = AddVertex(Position);
            }
            if (IDs[0] == IDs[1] || IDs[1] == IDs[2] || IDs[2] == IDs[0])
            {
                return true;
            }
            for (int32 Corner = 0; Corner < 3; ++Corner)
            {
                const int32 A = IDs[Corner];
                const int32 B = IDs[(Corner + 1) % 3];
                if (++EdgeUses.FindOrAdd(FIntPoint(FMath::Min(A, B), FMath::Max(A, B))) > 2)
                {
                    return false;
                }
            }
            return true;
        }

        bool AddMesh(UStaticMeshComponent* Component)
        {
            const UStaticMesh* Mesh = Component->GetStaticMesh();
            if (!Mesh || !Mesh->GetRenderData() || Mesh->GetRenderData()->LODResources.IsEmpty())
            {
                return false;
            }
            const FStaticMeshLODResources& LOD = Mesh->GetRenderData()->LODResources[0];
            const FIndexArrayView Indices = LOD.IndexBuffer.GetArrayView();
            UInstancedStaticMeshComponent* Instances =
                Cast<UInstancedStaticMeshComponent>(Component);
            const int32 Count = Instances ? Instances->GetInstanceCount() : 1;
            if (Count > MaxSourceInstances ||
                static_cast<int64>(Indices.Num()) * Count > MaxExpandedMeshIndices)
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
                    if (!AddTriangle(LOD, Indices, Index, Transform))
                    {
                        return false;
                    }
                }
            }
            return true;
        }
    };
} // namespace

FString InteriorFitSplineBoundaryExtractor::ExtractPlanarBoundary(const TArray<AActor*>& Sources)
{
    if (!IsInGameThread() || Sources.IsEmpty() || Sources.Num() > MaxBoundarySourceActors)
    {
        return InteriorFitSurfaceSampleJSON::Fail(
            LOCTEXT("InvalidInput", "请选择平面水体网格 Actor。").ToString());
    }
    UWorld* World = IsValid(Sources[0]) ? Sources[0]->GetWorld() : nullptr;
    if (!InteriorFitEditorWorld::IsEditorWorld(World))
    {
        return InteriorFitSurfaceSampleJSON::Fail(
            LOCTEXT("EditorWorld", "请在编辑器世界中执行。").ToString());
    }
    FPlanarSurfaceBoundary Boundary;
    for (AActor* Actor : Sources)
    {
        if (!IsValid(Actor) || Actor->GetWorld() != World)
        {
            return InteriorFitSurfaceSampleJSON::Fail(
                LOCTEXT("InvalidWaterSource", "水体来源无效。").ToString());
        }
        TInlineComponentArray<UStaticMeshComponent*> Components;
        Actor->GetComponents(Components);
        if (Components.IsEmpty())
        {
            return InteriorFitSurfaceSampleJSON::Fail(
                LOCTEXT("MissingLakeGeometry", "提取精确湖岸轮廓需要平面静态网格或已有样条。")
                    .ToString());
        }
        for (UStaticMeshComponent* Component : Components)
        {
            if (!IsValid(Component) || !Component->IsRegistered() || Component->IsEditorOnly())
            {
                continue;
            }
            if (!Boundary.AddMesh(Component))
            {
                return InteriorFitSurfaceSampleJSON::Fail(
                    LOCTEXT("InvalidLakeMesh", "湖面网格须水平、满足流形要求且在几何预算内。请选择"
                                               "湖面网格或使用已有闭合样条。")
                        .ToString());
            }
        }
    }
    TArray<TSharedPtr<FJsonValue>> Edges;
    for (const TPair<FIntPoint, int32>& Entry : Boundary.EdgeUses)
    {
        if (Entry.Value != 1)
        {
            continue;
        }
        TArray<TSharedPtr<FJsonValue>> Pair;
        Pair.Add(MakeShared<FJsonValueArray>(
            InteriorFitSurfaceSampleJSON::VectorJSON(Boundary.Positions[Entry.Key.X])));
        Pair.Add(MakeShared<FJsonValueArray>(
            InteriorFitSurfaceSampleJSON::VectorJSON(Boundary.Positions[Entry.Key.Y])));
        Edges.Add(MakeShared<FJsonValueArray>(Pair));
    }
    if (Edges.IsEmpty() || Edges.Num() > MaxBoundaryEdges)
    {
        const FText Error =
            FText::Format(LOCTEXT("BoundaryEdgeLimit",
                                  "湖岸边界须有 3 至 {0} 条边。请简化来源网格或使用已有样条。"),
                          FText::AsNumber(MaxBoundaryEdges));
        return InteriorFitSurfaceSampleJSON::Fail(Error.ToString());
    }
    TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
    Data->SetArrayField(TEXT("edges"), Edges);
    Data->SetNumberField(TEXT("triangles"), Boundary.TriangleCount);
    return InteriorFitSurfaceSampleJSON::Encode(Data);
}

#undef LOCTEXT_NAMESPACE
