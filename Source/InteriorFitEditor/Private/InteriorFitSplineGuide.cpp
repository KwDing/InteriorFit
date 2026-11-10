#include "InteriorFitSplineGuide.h"
#include "Components/SplineComponent.h"

AInteriorFitSplineGuide::AInteriorFitSplineGuide()
{
    Spline = CreateDefaultSubobject<USplineComponent>(TEXT("FittedSpline"));
    SetRootComponent(Spline);
    Spline->SetClosedLoop(false);
}
