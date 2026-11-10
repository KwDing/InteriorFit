#include "InteriorFitLibrary.h"
#include "Components/BrushComponent.h"
#include "Engine/Polys.h"
#include "GameFramework/Volume.h"
#include "Model.h"

namespace
{
struct FBarrierTriangle
{
    FVector A, B, C;
    TWeakObjectPtr<AVolume> Room;
};

TArray<FBarrierTriangle> ReadBarriers(const TArray<AActor*>& Rooms, const FBox& QueryBounds)
{
    TArray<FBarrierTriangle> Triangles;
    for (AActor* Actor : Rooms)
    {
        AVolume* Room = Cast<AVolume>(Actor);
        if (!IsValid(Room) || !Room->Brush || !Room->Brush->Polys) continue;
        // Cull distant Rooms before reading faces; never modify their physics state.
        if (!Room->GetBrushComponent()->Bounds.GetBox().Intersect(QueryBounds)) continue;
        const FTransform Transform = Room->GetActorTransform();
        for (const FPoly& Poly : Room->Brush->Polys->Element)
        {
            if (Poly.Vertices.Num() < 3) continue;
            const FVector A = Transform.TransformPosition(FVector(Poly.Vertices[0]));
            for (int32 Index = 1; Index + 1 < Poly.Vertices.Num(); ++Index)
                Triangles.Add({A, Transform.TransformPosition(FVector(Poly.Vertices[Index])),
                    Transform.TransformPosition(FVector(Poly.Vertices[Index + 1])), Room});
        }
    }
    return Triangles;
}

void ClipRay(const TArray<FBarrierTriangle>& Triangles, const FVector& Start, const FVector& End, FHitResult& Hit)
{
    double Closest = Hit.bBlockingHit ? FVector::DistSquared(Start, Hit.ImpactPoint) : FVector::DistSquared(Start, End);
    for (const FBarrierTriangle& Triangle : Triangles)
    {
        FVector Point, Normal;
        if (!FMath::SegmentTriangleIntersection(Start, End, Triangle.A, Triangle.B, Triangle.C, Point, Normal)) continue;
        const double Distance = FVector::DistSquared(Start, Point);
        if (Distance >= Closest || Distance < 0.0001) continue;
        AVolume* Room = Triangle.Room.Get();
        if (!Room) continue;
        Closest = Distance;
        if (FVector::DotProduct(Normal, End - Start) > 0) Normal = -Normal;
        Hit = FHitResult(Room, Room->GetBrushComponent(), Point, Normal);
        Hit.bBlockingHit = true;
        Hit.Distance = FMath::Sqrt(Distance);
        Hit.Time = Hit.Distance / FVector::Distance(Start, End);
        Hit.TraceStart = Start;
        Hit.TraceEnd = End;
    }
}
}

TArray<FHitResult> UInteriorFitLibrary::ConstrainRoomRays(const TArray<AActor*>& Rooms,
    const TArray<FVector>& Starts, const TArray<FVector>& Ends, const TArray<FHitResult>& PhysicalHits)
{
    if (!IsInGameThread() || Starts.Num() != Ends.Num() || Starts.Num() != PhysicalHits.Num()) return PhysicalHits;
    TArray<FHitResult> Results = PhysicalHits;
    FBox QueryBounds(ForceInit);
    for (int32 Index = 0; Index < Starts.Num(); ++Index) { QueryBounds += Starts[Index]; QueryBounds += Ends[Index]; }
    if (!QueryBounds.IsValid) return Results;
    const TArray<FBarrierTriangle> Triangles = ReadBarriers(Rooms, QueryBounds.ExpandBy(0.01));
    // Analytic segment/triangle tests, not extra world traces. Original async results remain nearest-hit candidates.
    for (int32 Index = 0; Index < Starts.Num(); ++Index) ClipRay(Triangles, Starts[Index], Ends[Index], Results[Index]);
    return Results;
}
