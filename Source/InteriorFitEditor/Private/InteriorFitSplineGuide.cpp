#include "InteriorFitSplineGuide.h"
#include "Components/SplineComponent.h"

AInteriorFitSplineGuide::AInteriorFitSplineGuide()
{
    PrimaryActorTick.bCanEverTick = false;
    Spline = CreateDefaultSubobject<USplineComponent>(TEXT("FittedSpline"));
    SetRootComponent(Spline);
    Spline->SetClosedLoop(false);
}
