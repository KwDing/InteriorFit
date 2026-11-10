#include "InteriorFitLibrary.h"
#include "Components/BrushComponent.h"
#include "GameFramework/Volume.h"
#include "PhysicsEngine/BodySetup.h"

namespace
{
// Numerical contact tolerance in cm, not a permissible overlap percentage.
constexpr double ContactTolerance = 0.001;
constexpr int32 MaxHulls = 64;
constexpr int32 MaxVertices = 256;
constexpr int32 MaxProjectionWork = 2000000;
constexpr double MinimumAxisLengthSquared = 1.e-16;
constexpr int32 Separated = 0;
constexpr int32 Overlapping = 1;
constexpr int32 Unsupported = -1;

struct FRoomHull
{
    TArray<FVector> Vertices;
    TArray<FVector> Normals;
    TArray<FVector> Edges;
    FBox Bounds = FBox(ForceInit);
};

void AddDirection(TArray<FVector>& Directions, const FVector& Value)
{
    if (Value.SizeSquared() <= MinimumAxisLengthSquared) return;
    const FVector Direction = Value.GetSafeNormal(MinimumAxisLengthSquared);
    for (const FVector& Existing : Directions)
        if (FMath::Abs(FVector::DotProduct(Existing, Direction)) > 1.0 - 1.e-10) return;
    Directions.Add(Direction);
}

bool ReadHull(const FKConvexElem& Element, const FTransform& World, FRoomHull& Hull)
{
    if (Element.VertexData.Num() < 4 || Element.VertexData.Num() > MaxVertices) return false;
    for (const FVector& Vertex : Element.VertexData)
    {
        const FVector Point = World.TransformPosition(Element.GetTransform().TransformPosition(Vertex));
        if (Point.ContainsNaN()) return false;
        Hull.Vertices.Add(Point);
        Hull.Bounds += Point;
    }
    const TArray<int32> Indices = Element.IndexData.IsEmpty() ? Element.GetChaosConvexIndices() : Element.IndexData;
    if (Indices.IsEmpty() || Indices.Num() % 3 || Indices.Num() > 1536) return false;
    for (int32 Index = 0; Index < Indices.Num(); Index += 3)
    {
        for (int32 Offset = 0; Offset < 3; ++Offset)
            if (!Hull.Vertices.IsValidIndex(Indices[Index + Offset])) return false;
        const FVector A = Hull.Vertices[Indices[Index]];
        const FVector B = Hull.Vertices[Indices[Index + 1]];
        const FVector C = Hull.Vertices[Indices[Index + 2]];
        AddDirection(Hull.Normals, FVector::CrossProduct(B - A, C - A));
        AddDirection(Hull.Edges, B - A);
        AddDirection(Hull.Edges, C - B);
        AddDirection(Hull.Edges, A - C);
    }
    return Hull.Normals.Num() >= 3 && Hull.Edges.Num() >= 3;
}

bool ReadRoom(AVolume* Room, TArray<FRoomHull>& Hulls)
{
    if (!IsValid(Room) || !Room->GetBrushComponent()) return false;
    UBrushComponent* Brush = Room->GetBrushComponent();
    const UBodySetup* Body = Brush->GetBodySetup();
    if (!Body || Body->AggGeom.ConvexElems.IsEmpty() || Body->AggGeom.ConvexElems.Num() > MaxHulls) return false;
    // Unsupported primitives must not silently disappear from an overlap decision.
    if (Body->AggGeom.GetElementCount() != Body->AggGeom.ConvexElems.Num()) return false;
    for (const FKConvexElem& Element : Body->AggGeom.ConvexElems)
    {
        FRoomHull Hull;
        if (!ReadHull(Element, Brush->GetComponentTransform(), Hull)) return false;
        Hulls.Add(MoveTemp(Hull));
    }
    return true;
}

bool BoxesSeparate(const FBox& A, const FBox& B)
{
    for (int32 Axis = 0; Axis < 3; ++Axis)
        if (FMath::Min(A.Max[Axis], B.Max[Axis]) - FMath::Max(A.Min[Axis], B.Min[Axis]) <= ContactTolerance) return true;
    return false;
}

FVector2D Interval(const TArray<FVector>& Vertices, const FVector& Axis, const FVector& Origin)
{
    FVector2D Range(DBL_MAX, -DBL_MAX);
    for (const FVector& Vertex : Vertices)
    {
        const double Value = FVector::DotProduct(Vertex - Origin, Axis);
        Range.X = FMath::Min(Range.X, Value);
        Range.Y = FMath::Max(Range.Y, Value);
    }
    return Range;
}

// SAT is complete for each convex pair: both face normals and all edge cross axes.
int32 TestAxis(const FRoomHull& A, const FRoomHull& B, const FVector& RawAxis, int32& Work)
{
    // Near-parallel edges have tiny cross products. Use the same squared-length
    // threshold for rejection and normalization: a zero axis cannot separate solids.
    if (RawAxis.SizeSquared() <= MinimumAxisLengthSquared) return Overlapping;
    Work += A.Vertices.Num() + B.Vertices.Num();
    if (Work > MaxProjectionWork) return Unsupported;
    const FVector Axis = RawAxis.GetSafeNormal(MinimumAxisLengthSquared);
    const FVector2D First = Interval(A.Vertices, Axis, A.Vertices[0]);
    const FVector2D Second = Interval(B.Vertices, Axis, A.Vertices[0]);
    return FMath::Min(First.Y, Second.Y) - FMath::Max(First.X, Second.X) > ContactTolerance ? Overlapping : Separated;
}

int32 HullOverlap(const FRoomHull& A, const FRoomHull& B, int32& Work)
{
    if (BoxesSeparate(A.Bounds, B.Bounds)) return Separated;
    for (const FVector& Normal : A.Normals)
    {
        const int32 Result = TestAxis(A, B, Normal, Work);
        if (Result != Overlapping) return Result;
    }
    for (const FVector& Normal : B.Normals)
    {
        const int32 Result = TestAxis(A, B, Normal, Work);
        if (Result != Overlapping) return Result;
    }
    for (const FVector& First : A.Edges)
        for (const FVector& Second : B.Edges)
        {
            const int32 Result = TestAxis(A, B, FVector::CrossProduct(First, Second), Work);
            if (Result != Overlapping) return Result;
        }
    return Overlapping;
}
}

int32 UInteriorFitLibrary::ClassifyRoomOverlap(AVolume* First, AVolume* Second)
{
    if (!IsInGameThread()) return Unsupported;
    TArray<FRoomHull> A;
    TArray<FRoomHull> B;
    if (!ReadRoom(First, A) || !ReadRoom(Second, B)) return Unsupported;
    int32 Work = 0;
    bool bUnknown = false;
    // Concave Rooms retain their collision decomposition; never hull the entire Room.
    for (const FRoomHull& Left : A)
        for (const FRoomHull& Right : B)
        {
            const int32 Result = HullOverlap(Left, Right, Work);
            if (Result == Overlapping) return Overlapping;
            bUnknown |= Result == Unsupported;
            if (Work > MaxProjectionWork) return Unsupported;
        }
    return bUnknown ? Unsupported : Separated;
}
