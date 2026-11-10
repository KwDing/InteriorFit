#include "InteriorFitLibrary.h"

#include "BSPOps.h"
#include "Components/BrushComponent.h"
#include "Editor.h"
#include "Engine/Polys.h"
#include "GameFramework/Volume.h"
#include "Model.h"
#include "ScopedTransaction.h"

namespace
{
constexpr double Tolerance = 0.1;

bool ReadBox(AVolume *Volume, const FTransform &Frame, FBox &Bounds)
{
    if (!Volume->Brush || !Volume->Brush->Polys || Volume->Brush->Polys->Element.Num() != 6)
        return false;
    TArray<FVector> Vertices;
    for (const FPoly &Face : Volume->Brush->Polys->Element)
    {
        if (Face.Vertices.Num() != 4)
            return false;
        for (const FVector3f &Local : Face.Vertices)
        {
            const FVector Point =
                Frame.InverseTransformPosition(Volume->GetActorTransform().TransformPosition(FVector(Local)));
            Bounds += Point;
            Vertices.Add(Point);
        }
    }
    if (Bounds.GetSize().GetMin() <= 2 * Tolerance)
        return false;
    TSet<int32> Corners;
    for (const FVector &Point : Vertices)
    {
        int32 Corner = 0;
        for (int Axis = 0; Axis < 3; ++Axis)
        {
            if (FMath::Abs(Point[Axis] - Bounds.Max[Axis]) <= Tolerance)
                Corner |= 1 << Axis;
            else if (FMath::Abs(Point[Axis] - Bounds.Min[Axis]) > Tolerance)
                return false;
        }
        Corners.Add(Corner);
    }
    return Corners.Num() == 8;
}

void EmitFace(TArray<FPoly> &Faces, const FVector &Min, const FVector &Max, int Axis, int Sign)
{
    FPoly Face;
    Face.Init();
    FVector Corner = Min;
    Corner[Axis] = Sign > 0 ? Max[Axis] : Min[Axis];
    const int U = (Axis + 1) % 3, V = (Axis + 2) % 3;
    Face.Vertices.Add(FVector3f(Corner));
    Corner[U] = Max[U];
    Face.Vertices.Add(FVector3f(Corner));
    Corner[V] = Max[V];
    Face.Vertices.Add(FVector3f(Corner));
    Corner[U] = Min[U];
    Face.Vertices.Add(FVector3f(Corner));
    Face.CalcNormal(1);
    if (Face.Normal[Axis] * Sign < 0)
        Face.Reverse();
    Face.Base = Face.Vertices[0];
    Faces.Add(MoveTemp(Face));
}
// Emit only exposed faces so the shared plane disappears and concave corners survive.
TArray<FPoly> UnionFaces(const FBox &A, const FBox &B, const TArray<double> (&Cuts)[3])
{
    TSet<FIntVector> Cells;
    auto Point = [&](FIntVector I) { return FVector(Cuts[0][I.X], Cuts[1][I.Y], Cuts[2][I.Z]); };
    const FIntVector One(1, 1, 1);
    for (int X = 0; X < Cuts[0].Num() - 1; ++X)
        for (int Y = 0; Y < Cuts[1].Num() - 1; ++Y)
            for (int Z = 0; Z < Cuts[2].Num() - 1; ++Z)
            {
                FIntVector I(X, Y, Z);
                FVector Center = (Point(I) + Point(I + One)) * 0.5;
                if (A.IsInside(Center) || B.IsInside(Center))
                    Cells.Add(I);
            }
    TArray<FPoly> Faces;
    for (const FIntVector &I : Cells)
        for (int Axis = 0; Axis < 3; ++Axis)
            for (int Sign : {-1, 1})
            {
                FIntVector Next = I;
                Next[Axis] += Sign;
                if (!Cells.Contains(Next))
                    EmitFace(Faces, Point(I), Point(I + One), Axis, Sign);
            }
    return Faces;
}

} // namespace

FString UInteriorFitLibrary::MergeTouchingBoxes(AVolume *First, AVolume *Second)
{
    if (!GEditor || GEditor->PlayWorld || !IsValid(First) || !IsValid(Second) || First == Second ||
        !First->GetWorld() || First->GetWorld()->WorldType != EWorldType::Editor ||
        First->GetLevel() != Second->GetLevel() || First->GetClass() != Second->GetClass())
        return TEXT("请选择同一编辑关卡中的两个同类型 Room。");
    FBox A(ForceInit), B(ForceInit);
    if (!ReadBox(First, First->GetActorTransform(), A) || !ReadBox(Second, First->GetActorTransform(), B))
        return TEXT("需要两个轴向一致的盒形 Brush。");
    int Contacts = 0;
    TArray<double> Cuts[3];
    for (int Axis = 0; Axis < 3; ++Axis)
    {
        const double Width = FMath::Min(A.Max[Axis], B.Max[Axis]) - FMath::Max(A.Min[Axis], B.Min[Axis]);
        if (Width < -Tolerance)
            return TEXT("两个 Room 之间存在间隙。");
        if (Width <= Tolerance)
            ++Contacts;
        auto &Values = Cuts[Axis];
        Values = {A.Min[Axis], A.Max[Axis], B.Min[Axis], B.Max[Axis]};
        Values.Sort();
        for (int i = Values.Num() - 1; i > 0; --i)
            if (Values[i] - Values[i - 1] <= Tolerance)
                Values.RemoveAt(i);
    }
    if (Contacts != 1)
        return TEXT("需要沿有面积的公共面接壤；不接受重叠或仅边角相碰。");
    TArray<FPoly> Faces = UnionFaces(A, B, Cuts);
    // Merge shared coplanar edges only when the resulting face stays convex.
    // This removes grid seams without filling the concave part of the union.
    FPoly::OptimizeIntoConvexPolys(First, Faces);
    FScopedTransaction Transaction(NSLOCTEXT("InteriorFit", "MergeBoxes", "合并接壤的 Room"));
    First->Modify();
    Second->Modify();
    if (!First->GetWorld()->EditorDestroyActor(Second, true))
        return TEXT("无法移除第二个 Room。");
    First->Brush->Modify();
    First->Brush->Polys->Modify();
    First->GetBrushComponent()->Modify();
    First->Brush->Polys->Element = MoveTemp(Faces);
    RefreshVolumeCollision(First);
    First->PostEditChange();
    First->MarkPackageDirty();
    GEditor->RedrawLevelEditingViewports();
    return {};
}
