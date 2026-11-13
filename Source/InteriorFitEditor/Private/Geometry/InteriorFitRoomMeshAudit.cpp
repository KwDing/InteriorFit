#include "InteriorFitRoomMeshAudit.h"

#include "UDynamicMesh.h"
#include "DynamicMesh/DynamicMesh3.h"
#include "DynamicMesh/DynamicMeshAABBTree3.h"
#include "Algo/Sort.h"
#include "Dom/JsonObject.h"
#include "Serialization/JsonSerializer.h"
#include "HAL/PlatformTime.h"

namespace
{
    using UE::Geometry::FDynamicMesh3;
    // Weld at 0.001 cm and ignore degenerate faces and tiny clipped-area slivers.
    constexpr int32 WeldGridStepsPerCm = 1000;
    constexpr double MinDoubleFaceAreaSquaredCm4 = 1.e-8;
    constexpr double CoplanarDistanceToleranceCm = 0.001;
    constexpr double MinDoubleOverlapAreaCm2 = 0.002;
    // Bounds the candidate work of the face-overlap audit.
    constexpr int32 MaxAuditTriangles = 2048;
    constexpr int32 MillisecondsPerSecond = 1000;

    struct FAudit
    {
        TArray<FVector> Vertices;
        TArray<FIntVector> Triangles;
        TMap<FIntVector, int32> Welded;
        TSet<FIntVector> UniqueFaces;
        TMap<FIntPoint, int32> EdgeUses;
        int32 Duplicates = 0;
        int32 Degenerate = 0;
        int32 CoplanarOverlaps = 0;

        int32 Vertex(const FVector& Point)
        {
            const FIntVector Key(FMath::RoundToInt(Point.X * WeldGridStepsPerCm),
                                 FMath::RoundToInt(Point.Y * WeldGridStepsPerCm),
                                 FMath::RoundToInt(Point.Z * WeldGridStepsPerCm));
            if (const int32* Existing = Welded.Find(Key))
            {
                return *Existing;
            }
            const int32 ID = Vertices.Add(Point);
            Welded.Add(Key, ID);
            return ID;
        }

        void Add(const FVector& A, const FVector& B, const FVector& C)
        {
            if (FVector::CrossProduct(B - A, C - A).SizeSquared() < MinDoubleFaceAreaSquaredCm4)
            {
                ++Degenerate;
                return;
            }
            FIntVector IDs(Vertex(A), Vertex(B), Vertex(C));
            if (IDs.X == IDs.Y || IDs.Y == IDs.Z || IDs.X == IDs.Z)
            {
                ++Degenerate;
                return;
            }
            int32 Ordered[] = {IDs.X, IDs.Y, IDs.Z};
            Algo::Sort(Ordered);
            const FIntVector Key(Ordered[0], Ordered[1], Ordered[2]);
            if (UniqueFaces.Contains(Key))
            {
                ++Duplicates;
                return;
            }
            UniqueFaces.Add(Key);
            Triangles.Add(IDs);
            for (int32 Index = 0; Index < 3; ++Index)
            {
                const int32 First = IDs[Index], Second = IDs[(Index + 1) % 3];
                ++EdgeUses.FindOrAdd(
                    FIntPoint(FMath::Min(First, Second), FMath::Max(First, Second)));
            }
        }
    };

    double Cross2(const FVector2D& A, const FVector2D& B)
    {
        return A.X * B.Y - A.Y * B.X;
    }

    TArray<FVector2D> Clip(const TArray<FVector2D>& Polygon, const FVector2D& A, const FVector2D& B,
                           double Sign)
    {
        TArray<FVector2D> Result;
        for (int32 Index = 0; Index < Polygon.Num(); ++Index)
        {
            const FVector2D P = Polygon[Index], Q = Polygon[(Index + 1) % Polygon.Num()];
            const double DP = Sign * Cross2(B - A, P - A), DQ = Sign * Cross2(B - A, Q - A);
            if (DP >= 0)
            {
                Result.Add(P);
            }
            if ((DP > 0 && DQ < 0) || (DP < 0 && DQ > 0))
            {
                Result.Add(P + (Q - P) * (DP / (DP - DQ)));
            }
        }
        return Result;
    }

    bool CoplanarOverlap(const FAudit& Audit, const FIntVector& First, const FIntVector& Second)
    {
        const FVector A = Audit.Vertices[First.X], B = Audit.Vertices[First.Y],
                      C = Audit.Vertices[First.Z];
        const FVector Normal = FVector::CrossProduct(B - A, C - A).GetSafeNormal();
        for (int32 ID : {Second.X, Second.Y, Second.Z})
        {
            if (FMath::Abs(FVector::DotProduct(Audit.Vertices[ID] - A, Normal)) >
                CoplanarDistanceToleranceCm)
            {
                return false;
            }
        }
        const FVector X = (B - A).GetSafeNormal(), Y = FVector::CrossProduct(Normal, X);
        auto Project = [&](const FVector& V)
        {
            return FVector2D(FVector::DotProduct(V - A, X), FVector::DotProduct(V - A, Y));
        };
        TArray<FVector2D> Polygon = {Project(A), Project(B), Project(C)};
        const TArray<FVector2D> Cutter = {Project(Audit.Vertices[Second.X]),
                                          Project(Audit.Vertices[Second.Y]),
                                          Project(Audit.Vertices[Second.Z])};
        const double Sign = Cross2(Cutter[1] - Cutter[0], Cutter[2] - Cutter[0]) >= 0 ? 1 : -1;
        for (int32 Index = 0; Index < 3 && !Polygon.IsEmpty(); ++Index)
        {
            Polygon = Clip(Polygon, Cutter[Index], Cutter[(Index + 1) % 3], Sign);
        }
        double Area = 0;
        for (int32 Index = 0; Index < Polygon.Num(); ++Index)
        {
            Area += Cross2(Polygon[Index], Polygon[(Index + 1) % Polygon.Num()]);
        }
        return FMath::Abs(Area) > MinDoubleOverlapAreaCm2;
    }

    int32 Components(const FAudit& Audit)
    {
        TArray<TArray<int32>> Adjacent;
        Adjacent.SetNum(Audit.Vertices.Num());
        for (const TPair<FIntPoint, int32>& Pair : Audit.EdgeUses)
        {
            Adjacent[Pair.Key.X].Add(Pair.Key.Y);
            Adjacent[Pair.Key.Y].Add(Pair.Key.X);
        }
        TSet<int32> Seen;
        int32 Count = 0;
        for (int32 Root = 0; Root < Adjacent.Num(); ++Root)
        {
            if (Seen.Contains(Root))
            {
                continue;
            }
            ++Count;
            TArray<int32> Pending = {Root};
            Seen.Add(Root);
            for (int32 Cursor = 0; Cursor < Pending.Num(); ++Cursor)
            {
                for (int32 Next : Adjacent[Pending[Cursor]])
                {
                    if (Seen.Contains(Next))
                    {
                        continue;
                    }
                    Seen.Add(Next);
                    Pending.Add(Next);
                }
            }
        }
        return Count;
    }

    int32 CountCoplanarOverlaps(const FAudit& Audit)
    {
        TArray<FBox> Bounds;
        TArray<int32> Order;
        FBox MeshBounds(ForceInit);
        for (const FIntVector& Triangle : Audit.Triangles)
        {
            FBox Box(ForceInit);
            Box += Audit.Vertices[Triangle.X];
            Box += Audit.Vertices[Triangle.Y];
            Box += Audit.Vertices[Triangle.Z];
            MeshBounds += Box;
            Order.Add(Bounds.Add(Box));
        }
        const FVector Size = MeshBounds.GetSize();
        int32 Axis = Size.X >= Size.Y ? 0 : 1;
        if (Size.Z > Size[Axis])
        {
            Axis = 2;
        }
        Order.Sort(
            [&Bounds, Axis](int32 A, int32 B)
            {
                return Bounds[A].Min[Axis] < Bounds[B].Min[Axis];
            });

        int32 Overlaps = 0;
        for (int32 Index = 0; Index < Order.Num(); ++Index)
        {
            const int32 A = Order[Index];
            // Include near-coplanar faces accepted by the exact plane-distance test.
            const FBox CandidateBounds = Bounds[A].ExpandBy(CoplanarDistanceToleranceCm);
            for (int32 Next = Index + 1; Next < Order.Num(); ++Next)
            {
                const int32 B = Order[Next];
                if (Bounds[B].Min[Axis] > CandidateBounds.Max[Axis])
                {
                    break;
                }
                if (CandidateBounds.Intersect(Bounds[B]))
                {
                    // The narrow phase projects onto the earlier face's plane.
                    Overlaps += CoplanarOverlap(Audit, Audit.Triangles[FMath::Min(A, B)],
                                                Audit.Triangles[FMath::Max(A, B)]);
                }
            }
        }
        return Overlaps;
    }

    FString Report(FAudit& Audit, double Started)
    {
        int32 OpenEdges = 0, NonManifold = 0;
        for (const TPair<FIntPoint, int32>& Pair : Audit.EdgeUses)
        {
            OpenEdges += Pair.Value == 1;
            NonManifold += Pair.Value > 2;
        }
        FDynamicMesh3 WeldedMesh;
        for (const FVector& V : Audit.Vertices)
        {
            WeldedMesh.AppendVertex(FVector3d(V));
        }
        bool bTopologyValid = true;
        for (const FIntVector& T : Audit.Triangles)
        {
            bTopologyValid &= WeldedMesh.AppendTriangle(T.X, T.Y, T.Z) >= 0;
        }
        Audit.CoplanarOverlaps = CountCoplanarOverlaps(Audit);
        UE::Geometry::FDynamicMeshAABBTree3 Tree(&WeldedMesh, true);
        const bool bCrossing = Tree.TestSelfIntersection(true);
        const TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
        Data->SetNumberField(TEXT("triangles"), Audit.Triangles.Num());
        Data->SetNumberField(TEXT("duplicate_faces"), Audit.Duplicates);
        Data->SetNumberField(TEXT("degenerate_faces"), Audit.Degenerate);
        Data->SetNumberField(TEXT("open_edges"), OpenEdges);
        Data->SetNumberField(TEXT("nonmanifold_edges"), NonManifold);
        Data->SetNumberField(TEXT("coplanar_overlaps"), Audit.CoplanarOverlaps);
        Data->SetBoolField(TEXT("crossing_faces"), bCrossing);
        const int32 ComponentCount = Components(Audit);
        Data->SetNumberField(TEXT("components"), ComponentCount);
        Data->SetBoolField(TEXT("valid"), bTopologyValid && ComponentCount == 1 && !OpenEdges &&
                                              !NonManifold && !Audit.Duplicates &&
                                              !Audit.Degenerate && !Audit.CoplanarOverlaps &&
                                              !bCrossing && Audit.Triangles.Num() >= 4);
        Data->SetNumberField(TEXT("elapsed_ms"),
                             (FPlatformTime::Seconds() - Started) * MillisecondsPerSecond);
        FString JSON;
        FJsonSerializer::Serialize(Data, TJsonWriterFactory<>::Create(&JSON));
        return JSON;
    }
} // namespace

FString InteriorFitRoomMeshAudit::AuditRoomMesh(UDynamicMesh* Mesh)
{
    if (!IsInGameThread() || !IsValid(Mesh))
    {
        return TEXT("{\"valid\":false,\"error\":\"Invalid mesh\"}");
    }
    const double Started = FPlatformTime::Seconds();
    FAudit Audit;
    const FDynamicMesh3* Source = Mesh->GetMeshPtr();
    if (!Source || Source->TriangleCount() > MaxAuditTriangles)
    {
        return FString::Printf(TEXT("{\"valid\":false,\"error\":\"Audit limit: %d triangles\"}"),
                               MaxAuditTriangles);
    }
    for (int32 ID : Source->TriangleIndicesItr())
    {
        FVector3d A, B, C;
        Source->GetTriVertices(ID, A, B, C);
        Audit.Add(FVector(A), FVector(B), FVector(C));
    }
    return Report(Audit, Started);
}
