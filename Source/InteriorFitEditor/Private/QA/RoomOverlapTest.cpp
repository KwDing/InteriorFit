#if WITH_DEV_AUTOMATION_TESTS
#include "InteriorFitLibrary.h"
#include "Engine/BlockingVolume.h"
#include "Engine/World.h"
#include "Misc/AutomationTest.h"
#include "Tests/AutomationEditorCommon.h"

namespace
{
AVolume* CreateBox(UWorld* World, const FVector& Extent)
{
    AVolume* Volume = UInteriorFitLibrary::CreateBoxVolume(
        World, ABlockingVolume::StaticClass(), FTransform::Identity, Extent);
    if (Volume) UInteriorFitLibrary::RefreshVolumeCollision(Volume);
    return Volume;
}

void CheckBothDirections(FAutomationTestBase& Test, AVolume* First, AVolume* Second, int32 Expected, const FString& Label)
{
    Test.TestEqual(Label + TEXT(" forward"), UInteriorFitLibrary::ClassifyRoomOverlap(First, Second), Expected);
    Test.TestEqual(Label + TEXT(" reverse"), UInteriorFitLibrary::ClassifyRoomOverlap(Second, First), Expected);
}
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRoomOverlapAxesTest, "InteriorFit.Geometry.RoomOverlap.NearParallel",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FRoomOverlapAxesTest::RunTest(const FString& Parameters)
{
    UWorld* World = FAutomationEditorCommonUtils::CreateNewMap();
    AVolume* First = CreateBox(World, FVector(100));
    AVolume* Second = CreateBox(World, FVector(100));
    if (!First || !Second) { AddError(TEXT("Could not construct native brush fixtures")); return false; }
    for (double Angle : {0.0, 0.0000001, 0.0001, 0.001, 0.01, 1.0, 37.0, 90.0})
    {
        Second->SetActorTransform(FTransform(FRotator(0, Angle, 0)));
        CheckBothDirections(*this, First, Second, 1, FString::Printf(TEXT("Coincident yaw %.7f"), Angle));
        Second->SetActorLocation(FVector(1000, 0, 0));
        CheckBothDirections(*this, First, Second, 0, FString::Printf(TEXT("Separated yaw %.7f"), Angle));
    }
    FAutomationEditorCommonUtils::CreateNewMap();
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FRoomOverlapBoundaryTest, "InteriorFit.Geometry.RoomOverlap.Boundaries",
    EAutomationTestFlags::EditorContext | EAutomationTestFlags::EngineFilter)
bool FRoomOverlapBoundaryTest::RunTest(const FString& Parameters)
{
    UWorld* World = FAutomationEditorCommonUtils::CreateNewMap();
    AVolume* First = CreateBox(World, FVector(100));
    AVolume* Second = CreateBox(World, FVector(100));
    if (!First || !Second) { AddError(TEXT("Could not construct native brush fixtures")); return false; }
    Second->SetActorLocation(FVector(200, 0, 0));
    CheckBothDirections(*this, First, Second, 0, TEXT("Face contact"));
    Second->SetActorLocation(FVector(199.99, 0, 0));
    CheckBothDirections(*this, First, Second, 1, TEXT("0.01 cm penetration"));
    Second->SetActorLocation(FVector(200.01, 0, 0));
    CheckBothDirections(*this, First, Second, 0, TEXT("0.01 cm gap"));
    Second->SetActorTransform(FTransform(FRotator(11, 37, 23), FVector::ZeroVector, FVector(.2, .3, .4)));
    CheckBothDirections(*this, First, Second, 1, TEXT("Rotated nonuniform containment"));
    TestEqual(TEXT("Missing collision is unknown"), UInteriorFitLibrary::ClassifyRoomOverlap(First, nullptr), -1);
    FAutomationEditorCommonUtils::CreateNewMap();
    return true;
}
#endif
