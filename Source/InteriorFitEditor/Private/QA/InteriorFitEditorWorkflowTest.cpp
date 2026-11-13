#if WITH_DEV_AUTOMATION_TESTS
#include "Misc/AutomationTest.h"
#include "InteriorFitLibrary.h"
#include "InteriorFitTraceBatch.h"
#include "Portals/InteriorFitOpeningPreview.h"
#include "Components/BoxComponent.h"
#include "Editor.h"
#include "Engine/World.h"
#include "Engine/Level.h"
#include "Components/LineBatchComponent.h"
#include "ToolMenus.h"
#include "Dom/JsonObject.h"
#include "DynamicMesh/DynamicMesh3.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "UDynamicMesh.h"

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FInteriorFitMenuTest, "InteriorFit.Menu.Unified",
                                 EAutomationTestFlags::EditorContext |
                                     EAutomationTestFlags::EngineFilter)
bool FInteriorFitMenuTest::RunTest(const FString& Parameters)
{
    UToolMenu* Menu = UToolMenus::Get()->FindMenu(TEXT("LevelEditor.ActorContextMenu"));
    if (!TestNotNull(TEXT("Actor context menu"), Menu))
    {
        return false;
    }
    FToolMenuSection* Section = Menu->FindSection(TEXT("InteriorFit"));
    if (!TestNotNull(TEXT("Audio tools section"), Section))
    {
        return false;
    }
    TestEqual(TEXT("One top-level entry"), Section->Blocks.Num(), 1);
    FToolMenuEntry* Entry = Section->FindEntry(TEXT("AudioAutoFit"));
    if (!TestNotNull(TEXT("Audio Auto Fit"), Entry))
    {
        return false;
    }
    TestTrue(TEXT("Entry is a submenu"), Entry->IsSubMenu());
    UToolMenu* SubMenu = NewObject<UToolMenu>();
    Entry->SubMenuData.ConstructMenu.NewToolMenu.Execute(SubMenu);
    auto HasEntry = [](const UToolMenu* InMenu, FName Name)
    {
        for (const FToolMenuSection& Item : InMenu->Sections)
        {
            if (Item.FindEntry(Name))
            {
                return true;
            }
        }
        return false;
    };
    for (const TCHAR* Name : {TEXT("PreviewRoom"), TEXT("ContourFit"), TEXT("CreateRoom"),
                              TEXT("FindOpenings"), TEXT("FitOpenings"), TEXT("TestLake"),
                              TEXT("TestRiver"), TEXT("TestArea"), TEXT("ClearPreview")})
    {
        TestTrue(Name, HasEntry(SubMenu, FName(Name)));
    }
    TestFalse(TEXT("No project surface audio setup"), HasEntry(SubMenu, TEXT("PreviewSurface")));
    TestFalse(TEXT("No project surface audio creation"), HasEntry(SubMenu, TEXT("ApplySurface")));
    TestEqual(TEXT("House, surface and cleanup sections"), SubMenu->Sections.Num(), 3);
    if (UToolMenu* Assets = UToolMenus::Get()->FindMenu(TEXT("ContentBrowser.AssetContextMenu")))
    {
        TestFalse(TEXT("No obsolete AreaPreset action"),
                  HasEntry(Assets, TEXT("InteriorFitSoundPreset")));
    }
    return true;
}

IMPLEMENT_SIMPLE_AUTOMATION_TEST(FInteriorFitPreviewTest, "InteriorFit.Preview.AllBoxes",
                                 EAutomationTestFlags::EditorContext |
                                     EAutomationTestFlags::EngineFilter)
bool FInteriorFitPreviewTest::RunTest(const FString& Parameters)
{
    UWorld* World = GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
    if (!TestNotNull(TEXT("Editor world"), World))
    {
        return false;
    }
    const int32 ActorCount = World->PersistentLevel->Actors.Num();
    const FString Rows = TEXT(R"([
        {"center":[0,0,100],"half_extent":[20,50,100],"yaw":0,"open":true,"blocked":false},
        {"center":[1000,1000,100],"half_extent":[20,50,100],"yaw":90,"open":false,"blocked":true},
        {"center":[-1000,1000,100],"half_extent":[20,50,100],"yaw":45,"open":false,"blocked":false}
    ])");
    auto Count = [World]()
    {
        int32 Result = 0;
        for (const FBatchedLine& Line : World->PersistentLineBatcher->BatchedLines)
        {
            if (Line.BatchID == InteriorFitOpeningPreview::OpeningBatchID)
            {
                ++Result;
            }
        }
        return Result;
    };
    TestTrue(TEXT("Draw mixed open/closed/blocked rows"),
             UInteriorFitLibrary::DrawOpeningPreviews(World, Rows));
    TestEqual(TEXT("All three boxes have twelve edges"), Count(), 36);
    UInteriorFitLibrary::DrawOpeningPreviews(World, Rows);
    TestEqual(TEXT("Repeat replaces, does not accumulate"), Count(), 36);
    UInteriorFitLibrary::DrawOpeningPreviews(World, TEXT("[]"));
    TestEqual(TEXT("Clear removes all preview edges"), Count(), 0);
    TestEqual(TEXT("No preview Actors created"), World->PersistentLevel->Actors.Num(), ActorCount);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FInteriorFitAsyncTest, "InteriorFit.Contour.AsyncRayBatch",
                                 EAutomationTestFlags::EditorContext |
                                     EAutomationTestFlags::EngineFilter)
bool FInteriorFitAsyncTest::RunTest(const FString&)
{
    UWorld* World = UWorld::CreateWorld(EWorldType::Editor, false);
    if (!TestNotNull(TEXT("Isolated physics world"), World))
    {
        return false;
    }
    GEngine->CreateNewWorldContext(EWorldType::Editor).SetCurrentWorld(World);
    AActor* Floor = World->SpawnActor<AActor>();
    UBoxComponent* Box = NewObject<UBoxComponent>(Floor);
    Floor->SetRootComponent(Box);
    Box->SetBoxExtent(FVector(50));
    Box->SetCollisionProfileName(TEXT("BlockAll"));
    Box->RegisterComponent();
    AActor* Seed = World->SpawnActor<AActor>();
    FInteriorFitTraceRequest Request;
    Request.Starts = {FVector(0, 0, 100), FVector(300, 0, 100)};
    Request.Ends = {FVector(0, 0, -100), FVector(300, 0, -100)};
    UInteriorFitTraceBatch* Batch = UInteriorFitTraceBatch::SubmitRequest(Seed, Request);
    if (TestNotNull(TEXT("Submitted batch"), Batch))
    {
        World->Tick(LEVELTICK_ViewportsOnly, 1.f / 60);
        World->Tick(LEVELTICK_ViewportsOnly, 1.f / 60);
        TestEqual(TEXT("Both callbacks delivered"), Batch->Pending, 0);
        TestFalse(TEXT("Used native async path"), Batch->bFrameSliced);
        TestTrue(TEXT("Hit and miss retain request order"),
                 Batch->Hits[0].bBlockingHit && !Batch->Hits[1].bBlockingHit);
    }
    GEngine->DestroyWorldContext(World);
    World->DestroyWorld(false);
    return true;
}
IMPLEMENT_SIMPLE_AUTOMATION_TEST(FInteriorFitMeshAuditTest,
                                 "InteriorFit.Geometry.MeshAudit.CoplanarBounds",
                                 EAutomationTestFlags::EditorContext |
                                     EAutomationTestFlags::EngineFilter)

bool FInteriorFitMeshAuditTest::RunTest(const FString&)
{
    UE::Geometry::FDynamicMesh3 Mesh;
    const auto AddFace = [&Mesh](double OffsetX, double OffsetZ)
    {
        const int32 A = Mesh.AppendVertex(FVector3d(OffsetX, 0, OffsetZ));
        const int32 B = Mesh.AppendVertex(FVector3d(OffsetX + 10, 0, OffsetZ));
        const int32 C = Mesh.AppendVertex(FVector3d(OffsetX, 10, OffsetZ));
        Mesh.AppendTriangle(A, B, C);
    };
    AddFace(0, 0);
    AddFace(1, 0.0008);
    AddFace(100, 0);
    UDynamicMesh* Input = NewObject<UDynamicMesh>();
    Input->SetMesh(MoveTemp(Mesh));

    TSharedPtr<FJsonObject> Result;
    const FString JSON = UInteriorFitLibrary::AuditRoomMesh(Input);
    if (!TestTrue(TEXT("Audit JSON"),
                  FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(JSON), Result)) ||
        !Result.IsValid())
    {
        return false;
    }
    TestEqual(TEXT("Only the near-coplanar overlapping pair is counted"),
              Result->GetIntegerField(TEXT("coplanar_overlaps")), 1);
    return true;
}
#endif
