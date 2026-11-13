#include "Modules/ModuleManager.h"

#include "Interfaces/IPluginManager.h"
#include "InteriorFitEditorLog.h"
#include "InteriorFitEditorPython.h"
#include "Misc/Paths.h"
#include "ToolMenus.h"
#include "InteriorFitOpeningsPanel.h"

DEFINE_LOG_CATEGORY(LogInteriorFit);

#define LOCTEXT_NAMESPACE "InteriorFitEditor"

namespace
{
    void RunInteriorFit(const TCHAR* Function)
    {
        const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("InteriorFit"));
        if (!Plugin.IsValid())
        {
            UE_LOG(LogInteriorFit, Error, TEXT("Cannot locate the Interior Fit plugin directory."));
            return;
        }
        const FString Path =
            FPaths::ConvertRelativePathToFull(Plugin->GetBaseDir() / TEXT("Content/Python"));
        const FString EscapedPath =
            Path.Replace(TEXT("\\"), TEXT("/")).Replace(TEXT("'"), TEXT("\\'"));
        const FString Command = FString::Printf(
            TEXT("import sys; sys.path.insert(0, '%s') if '%s' not in sys.path else None; "
                 "import interior_fit.editor as fit; fit.%s()"),
            *EscapedPath, *EscapedPath, Function);
        InteriorFitEditorPython::Execute(Command);
    }

    void AddEntry(FToolMenuSection& Section, FName Name, const FText& Label, const TCHAR* Function,
                  const FText& Tooltip)
    {
        Section.AddMenuEntry(Name, Label, Tooltip, FSlateIcon(),
                             FUIAction(FExecuteAction::CreateLambda(
                                 [Function]
                                 {
                                     RunInteriorFit(Function);
                                 })));
    }

    void PopulateAudioAutoFit(UToolMenu* Menu)
    {
        FToolMenuSection& Rooms =
            Menu->AddSection(TEXT("Rooms"), LOCTEXT("RoomsSection", "房屋声学"));
        AddEntry(Rooms, TEXT("PreviewRoom"), LOCTEXT("PreviewRoomLabel", "预览室内范围"),
                 TEXT("preview_selected"),
                 LOCTEXT("PreviewRoomTooltip",
                         "选择房间内的种子对象，检查墙面、地板和顶面；不修改地图。"));
        AddEntry(
            Rooms, TEXT("ContourFit"), LOCTEXT("ContourFitLabel", "拟合多边形 Room…"),
            TEXT("fit_polygon_selected"),
            LOCTEXT("ContourFitTooltip", "从选中种子异步扫描地板和顶板，确认后创建多边形 Room。"));
        AddEntry(Rooms, TEXT("FloorRooms"),
                 LOCTEXT("FloorRoomsLabel", "从一个种子制作本层 Rooms 与门…"),
                 TEXT("fit_floor_selected"),
                 LOCTEXT("FloorRoomsTooltip",
                         "沿有门楣的开口探测同层相邻房间，保留已有 Room，再统一审核 Portal。"));
        AddEntry(Rooms, TEXT("StairRooms"), LOCTEXT("StairRoomsLabel", "探测楼梯间 Room…"),
                 TEXT("fit_stair_selected"),
                 LOCTEXT("StairRoomsTooltip", "从平台或踏步种子跟踪多层空气区间。"));
        AddEntry(
            Rooms, TEXT("MergeRooms"), LOCTEXT("MergeRoomsLabel", "合并两个接壤的盒形 Room…"),
            TEXT("merge_selected_rooms"),
            LOCTEXT("MergeRoomsTooltip",
                    "简化共面分割并清理明确的内部 Portal，保留第一个 Room 的设置；支持撤销。"));
        AddEntry(Rooms, TEXT("CreateRoom"), LOCTEXT("CreateRoomLabel", "创建 Wwise Room…"),
                 TEXT("create_selected"),
                 LOCTEXT("CreateRoomTooltip",
                         "通过拟合检查后创建原生 Room。已有 Room 的位置不会重复创建。"));
        AddEntry(Rooms, TEXT("FindOpenings"), LOCTEXT("FindOpeningsLabel", "检测 Room 门窗…"),
                 TEXT("find_openings_selected"),
                 LOCTEXT("FindOpeningsTooltip", "从所选 Room 查找开口，检查候选后创建 Portal。"));
        AddEntry(Rooms, TEXT("FitOpenings"), LOCTEXT("FitOpeningsLabel", "拟合所选门窗…"),
                 TEXT("fit_openings_selected"),
                 LOCTEXT("FitOpeningsTooltip", "选择门窗网格，检查开口和 Room 关联。"));
        FToolMenuSection& Surfaces =
            Menu->AddSection(TEXT("Surfaces"), LOCTEXT("SurfacesSection", "草地 / 水面 / 雪地"));
        AddEntry(Surfaces, TEXT("TestLake"), LOCTEXT("TestLakeLabel", "拟合湖岸闭合样条"),
                 TEXT("fit_lake_geometry"),
                 LOCTEXT("TestLakeTooltip", "从选中水平水面生成几何样条。"));
        AddEntry(Surfaces, TEXT("TestRiver"), LOCTEXT("TestRiverLabel", "拟合河网中心样条"),
                 TEXT("fit_river_geometry"),
                 LOCTEXT("TestRiverTooltip", "从选中河面提取分叉中心线。"));
        AddEntry(Surfaces, TEXT("TestArea"), LOCTEXT("TestAreaLabel", "拟合地表 Area"),
                 TEXT("fit_area_geometry"),
                 LOCTEXT("TestAreaTooltip", "采样选中表面并创建纯几何区域。"));
        FToolMenuSection& Preview = Menu->AddSection(TEXT("Preview"));
        AddEntry(Preview, TEXT("ClearPreview"), LOCTEXT("ClearPreviewLabel", "清除预览"),
                 TEXT("clear_preview"),
                 LOCTEXT("ClearPreviewTooltip", "清除 Room、门窗和地表预览，不删除已创建对象。"));
    }

    void PopulateViewFit(UToolMenu* Menu)
    {
        FToolMenuSection& Section =
            Menu->AddSection(TEXT("ViewFit"), LOCTEXT("ViewSection", "从当前透视视口开始"));
        AddEntry(Section, TEXT("AcceptBoundaryCandidate"),
                 LOCTEXT("AcceptBoundaryCandidateLabel", "采纳所选 Room 候选…"),
                 TEXT("accept_boundary_review"),
                 LOCTEXT("AcceptBoundaryCandidateTooltip", "检查橙色边界后，仅为本候选确认超差。"));
        AddEntry(Section, TEXT("ViewRoom"), LOCTEXT("ViewRoomLabel", "拟合当前位置的 Room…"),
                 TEXT("fit_view_room"),
                 LOCTEXT("ViewRoomTooltip", "飞入房间即可采样，预览后确认创建。"));
        AddEntry(Section, TEXT("ViewStair"), LOCTEXT("ViewStairLabel", "探测当前位置的楼梯间…"),
                 TEXT("fit_view_stair"),
                 LOCTEXT("ViewStairTooltip", "将视口移至下平台，沿踏步寻找连通的平台。"));
        AddEntry(Section, TEXT("ViewFloor"),
                 LOCTEXT("ViewFloorLabel", "制作当前位置的本层 Rooms 与门…"),
                 TEXT("fit_view_floor"),
                 LOCTEXT("ViewFloorTooltip", "从视口所在房间向相邻门洞扩展，完成后审核 Portal。"));
    }

} // namespace

class FInteriorFitEditorModule : public IModuleInterface
{
  public:
    void StartupModule() override
    {
        if (IsRunningCommandlet())
        {
            return;
        }
        InteriorFitOpenings::Register();
        UToolMenus::RegisterStartupCallback(FSimpleMulticastDelegate::FDelegate::CreateRaw(
            this, &FInteriorFitEditorModule::RegisterMenus));
    }

    void ShutdownModule() override
    {
        if (IsRunningCommandlet())
        {
            return;
        }
        UToolMenus::UnRegisterStartupCallback(this);
        UToolMenus::UnregisterOwner(this);
        InteriorFitOpenings::Shutdown();
    }

  private:
    void RegisterMenus()
    {
        FToolMenuOwnerScoped Owner(this);
        FToolMenuSection& Tools = UToolMenus::Get()
                                      ->ExtendMenu(TEXT("LevelEditor.MainMenu.Tools"))
                                      ->FindOrAddSection(TEXT("InteriorFit"));
        Tools.AddSubMenu(TEXT("AudioAutoFitView"), LOCTEXT("ToolLabel", "Audio Auto Fit"),
                         LOCTEXT("ViewToolTooltip", "使用编辑器视口位置自动生成种子并开始拟合"),
                         FNewToolMenuDelegate::CreateStatic(&PopulateViewFit));
        FToolMenuSection& Section = UToolMenus::Get()
                                        ->ExtendMenu(TEXT("LevelEditor.ActorContextMenu"))
                                        ->FindOrAddSection(TEXT("InteriorFit"));
        Section.AddSubMenu(TEXT("AudioAutoFit"), LOCTEXT("ToolLabel", "Audio Auto Fit"),
                           LOCTEXT("ActorToolTooltip", "房屋 Room / Portal 与地表几何制作"),
                           FNewToolMenuDelegate::CreateStatic(&PopulateAudioAutoFit));
    }
};

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FInteriorFitEditorModule, InteriorFitEditor)
