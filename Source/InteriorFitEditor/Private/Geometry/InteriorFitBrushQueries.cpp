#include "InteriorFitBrushQueries.h"

#include "GameFramework/Volume.h"
#include "Model.h"

int32 InteriorFitBrushQueries::CountBrushTriangles(AVolume* Volume)
{
    if (!IsValid(Volume) || !Volume->Brush)
    {
        return 0;
    }
    int32 Count = 0;
    for (const FBspNode& Node : Volume->Brush->Nodes)
    {
        Count += FMath::Max(0, static_cast<int32>(Node.NumVertices) - 2);
    }
    return Count;
}

bool InteriorFitBrushQueries::ContainsPoint(AVolume* Volume, FVector Position)
{
    return IsInGameThread() && IsValid(Volume) && !Position.ContainsNaN() &&
           Volume->EncompassesPoint(Position);
}
