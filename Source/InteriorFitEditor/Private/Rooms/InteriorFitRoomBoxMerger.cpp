#include "InteriorFitRoomBoxMerger.h"

#include "InteriorFitEditorWorld.h"

#include "BSPOps.h"
#include "Components/BrushComponent.h"
#include "Editor.h"
#include "Engine/Polys.h"
#include "Engine/World.h"
#include "GameFramework/Volume.h"
#include "Model.h"
#include "ScopedTransaction.h"
#include "InteriorFitVolumeAuthoring.h"

namespace
{
    constexpr double BoxMergeToleranceCm = 0.1;

    bool ReadBox(AVolume* Volume, const FTransform& Frame, FBox& Bounds)
    {
        if (!Volume->Brush || !Volume->Brush->Polys || Volume->Brush->Polys->Element.Num() != 6)
        {
            return false;
        }
        TArray<FVector> Vertices;
        for (const FPoly& Face : Volume->Brush->Polys->Element)
        {
            if (Face.Vertices.Num() != 4)
            {
                return false;
            }
            for (const FVector3f& Local : Face.Vertices)
            {
                const FVector Point = Frame.InverseTransformPosition(
                    Volume->GetActorTransform().TransformPosition(FVector(Local)));
                Bounds += Point;
                Vertices.Add(Point);
            }
        }
        if (Bounds.GetSize().GetMin() <= 2 * BoxMergeToleranceCm)
        {
            return false;
        }
        TSet<int32> Corners;
        for (const FVector& Point : Vertices)
        {
            int32 Corner = 0;
            for (int32 Axis = 0; Axis < 3; ++Axis)
            {
                if (FMath::Abs(Point[Axis] - Bounds.Max[Axis]) <= BoxMergeToleranceCm)
                {
                    Corner |= 1 << Axis;
                }
                else if (FMath::Abs(Point[Axis] - Bounds.Min[Axis]) > BoxMergeToleranceCm)
                {
                    return false;
                }
            }
            Corners.Add(Corner);
        }
        return Corners.Num() == 8;
    }

    void EmitFace(TArray<FPoly>& Faces, const FVector& Min, const FVector& Max, int32 Axis,
                  int32 Sign)
    {
        FPoly Face;
        Face.Init();
        FVector Corner = Min;
        Corner[Axis] = Sign > 0 ? Max[Axis] : Min[Axis];
        const int32 U = (Axis + 1) % 3, V = (Axis + 2) % 3;
        Face.Vertices.Add(FVector3f(Corner));
        Corner[U] = Max[U];
        Face.Vertices.Add(FVector3f(Corner));
        Corner[V] = Max[V];
        Face.Vertices.Add(FVector3f(Corner));
        Corner[U] = Min[U];
        Face.Vertices.Add(FVector3f(Corner));
        Face.CalcNormal(1);
        if (Face.Normal[Axis] * Sign < 0)
        {
            Face.Reverse();
        }
        Face.Base = Face.Vertices[0];
        Faces.Add(MoveTemp(Face));
    }
    const FIntVector CellDiagonal(1, 1, 1);

    FVector GridPoint(const TArray<double> (&Cuts)[3], const FIntVector& Index)
    {
        return FVector(Cuts[0][Index.X], Cuts[1][Index.Y], Cuts[2][Index.Z]);
    }

    TSet<FIntVector> CollectUnionCells(const FBox& A, const FBox& B,
                                       const TArray<double> (&Cuts)[3])
    {
        TSet<FIntVector> Cells;
        const int32 CountX = Cuts[0].Num() - 1;
        const int32 CountY = Cuts[1].Num() - 1;
        const int32 CountZ = Cuts[2].Num() - 1;
        for (int32 Cell = 0; Cell < CountX * CountY * CountZ; ++Cell)
        {
            const FIntVector Index(Cell / (CountY * CountZ), Cell / CountZ % CountY, Cell % CountZ);
            const FVector Center =
                (GridPoint(Cuts, Index) + GridPoint(Cuts, Index + CellDiagonal)) * 0.5;
            if (A.IsInside(Center) || B.IsInside(Center))
            {
                Cells.Add(Index);
            }
        }
        return Cells;
    }

    // Emit only exposed faces so the shared plane disappears and concave corners survive.
    TArray<FPoly> UnionFaces(const FBox& A, const FBox& B, const TArray<double> (&Cuts)[3])
    {
        const TSet<FIntVector> Cells = CollectUnionCells(A, B, Cuts);
        TArray<FPoly> Faces;
        for (const FIntVector& Index : Cells)
        {
            const FVector Min = GridPoint(Cuts, Index);
            const FVector Max = GridPoint(Cuts, Index + CellDiagonal);
            for (int32 Side = 0; Side < 6; ++Side)
            {
                const int32 Axis = Side / 2;
                const int32 Sign = Side % 2 ? 1 : -1;
                FIntVector Neighbor = Index;
                Neighbor[Axis] += Sign;
                if (!Cells.Contains(Neighbor))
                {
                    EmitFace(Faces, Min, Max, Axis, Sign);
                }
            }
        }
        return Faces;
    }

} // namespace

FString InteriorFitRoomBoxMerger::MergeTouchingBoxes(AVolume* First, AVolume* Second)
{
    const bool bValidPair = IsValid(First) && IsValid(Second) && First != Second;
    if (!GEditor || GEditor->PlayWorld || !bValidPair)
    {
        return TEXT("请选择同一编辑关卡中的两个同类型 Room。");
    }
    UWorld* World = First->GetWorld();
    const bool bSameLevelAndType =
        First->GetLevel() == Second->GetLevel() && First->GetClass() == Second->GetClass();
    if (!InteriorFitEditorWorld::IsEditorWorld(World) || !bSameLevelAndType)
    {
        return TEXT("请选择同一编辑关卡中的两个同类型 Room。");
    }
    UBrushComponent* Brush = First->GetBrushComponent();
    if (!IsValid(Brush))
    {
        return TEXT("第一个 Room 缺少 Brush 组件。");
    }
    FBox A(ForceInit), B(ForceInit);
    if (!ReadBox(First, First->GetActorTransform(), A) ||
        !ReadBox(Second, First->GetActorTransform(), B))
    {
        return TEXT("需要两个轴向一致的盒形 Brush。");
    }
    int32 Contacts = 0;
    TArray<double> Cuts[3];
    for (int32 Axis = 0; Axis < 3; ++Axis)
    {
        const double Width =
            FMath::Min(A.Max[Axis], B.Max[Axis]) - FMath::Max(A.Min[Axis], B.Min[Axis]);
        if (Width < -BoxMergeToleranceCm)
        {
            return TEXT("两个 Room 之间存在间隙。");
        }
        if (Width <= BoxMergeToleranceCm)
        {
            ++Contacts;
        }
        TArray<double>& Values = Cuts[Axis];
        Values = {A.Min[Axis], A.Max[Axis], B.Min[Axis], B.Max[Axis]};
        Values.Sort();
        for (int32 i = Values.Num() - 1; i > 0; --i)
        {
            if (Values[i] - Values[i - 1] <= BoxMergeToleranceCm)
            {
                Values.RemoveAt(i);
            }
        }
    }
    if (Contacts != 1)
    {
        return TEXT("需要沿有面积的公共面接壤；不接受重叠或仅边角相碰。");
    }
    TArray<FPoly> Faces = UnionFaces(A, B, Cuts);
    // Merge shared coplanar edges only when the resulting face stays convex.
    // This removes grid seams without filling the concave part of the union.
    FPoly::OptimizeIntoConvexPolys(First, Faces);
    FScopedTransaction Transaction(NSLOCTEXT("InteriorFit", "MergeBoxes", "合并接壤的 Room"));
    First->Modify();
    Second->Modify();
    if (!World->EditorDestroyActor(Second, true))
    {
        return TEXT("无法移除第二个 Room。");
    }
    First->Brush->Modify();
    First->Brush->Polys->Modify();
    Brush->Modify();
    First->Brush->Polys->Element = MoveTemp(Faces);
    InteriorFitVolumeAuthoring::RefreshVolumeCollision(First);
    First->PostEditChange();
    First->MarkPackageDirty();
    GEditor->RedrawLevelEditingViewports();
    return {};
}
