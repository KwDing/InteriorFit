#include "Modules/ModuleManager.h"

#include "Interfaces/IPluginManager.h"
#include "IPythonScriptPlugin.h"
#include "Misc/MessageDialog.h"
#include "Misc/Paths.h"
#include "ToolMenus.h"
#include "InteriorFitOpeningsPanel.h"

namespace
{
    void RunInteriorFit(const TCHAR* Function)
    {
        const TSharedPtr<IPlugin> Plugin = IPluginManager::Get().FindPlugin(TEXT("InteriorFit"));
        IPythonScriptPlugin* Python = IPythonScriptPlugin::Get();
        if (!Plugin.IsValid() || !Python || !Python->IsPythonAvailable())
        {
            FMessageDialog::Open(EAppMsgType::Ok, FText::FromString(TEXT("Interior Fit requires Python Editor Script Plugin. Enable it and restart the editor.")));
            return;
        }
        const FString Path = FPaths::ConvertRelativePathToFull(Plugin->GetBaseDir() / TEXT("Content/Python"));
        const FString EscapedPath = Path.Replace(TEXT("\\"), TEXT("/")).Replace(TEXT("'"), TEXT("\\'"));
        const FString Command = FString::Printf(TEXT("import sys; sys.path.insert(0, '%s') if '%s' not in sys.path else None; import interior_fit.editor as fit; fit.%s()"),
            *EscapedPath, *EscapedPath, Function);
        Python->ExecPythonCommand(*Command);
    }

    void AddEntry(FToolMenuSection& Section, FName Name, const TCHAR* Label, const TCHAR* Function, const TCHAR* Tooltip)
    {
        Section.AddMenuEntry(Name, FText::FromString(Label), FText::FromString(Tooltip),
            FSlateIcon(), FUIAction(FExecuteAction::CreateLambda([Function] { RunInteriorFit(Function); })));
    }

    void PopulateAudioAutoFit(UToolMenu* Menu)
    {
        auto& Rooms = Menu->AddSection(TEXT("Rooms"), FText::FromString(TEXT("房屋声学")));
        AddEntry(Rooms, TEXT("PreviewRoom"), TEXT("预览室内范围"), TEXT("preview_selected"), TEXT("选择房间内的种子对象，检查墙面、地板和顶面；不修改地图。"));
        AddEntry(Rooms, TEXT("ContourFit"), TEXT("拟合多边形 Room…"), TEXT("fit_polygon_selected"), TEXT("从选中种子异步扫描地板和顶板，确认后创建多边形 Room。"));
        AddEntry(Rooms, TEXT("FloorRooms"), TEXT("从一个种子制作本层 Rooms 与门…"), TEXT("fit_floor_selected"), TEXT("沿有门楣的开口探测同层相邻房间，保留已有 Room，再统一审核 Portal。"));
        AddEntry(Rooms, TEXT("StairRooms"), TEXT("探测楼梯间 Room…"), TEXT("fit_stair_selected"), TEXT("从平台或踏步种子跟踪多层空气区间。"));
        AddEntry(Rooms, TEXT("MergeRooms"), TEXT("合并两个接壤的盒形 Room…"), TEXT("merge_selected_rooms"), TEXT("简化共面分割并清理明确的内部 Portal，保留第一个 Room 的设置；支持撤销。"));
        AddEntry(Rooms, TEXT("CreateRoom"), TEXT("创建 Wwise Room…"), TEXT("create_selected"), TEXT("通过拟合检查后创建原生 Room。已有 Room 的位置不会重复创建。"));
        AddEntry(Rooms, TEXT("FindOpenings"), TEXT("检测 Room 门窗…"), TEXT("find_openings_selected"), TEXT("从所选 Room 查找开口，检查候选后创建 Portal。"));
        AddEntry(Rooms, TEXT("FitOpenings"), TEXT("拟合所选门窗…"), TEXT("fit_openings_selected"), TEXT("选择门窗网格，检查开口和 Room 关联。"));
        auto& Surfaces = Menu->AddSection(TEXT("Surfaces"), FText::FromString(TEXT("草地 / 水面 / 雪地")));
        AddEntry(Surfaces, TEXT("TestLake"), TEXT("拟合湖岸闭合样条"), TEXT("fit_lake_geometry"), TEXT("从选中水平水面生成几何样条。"));
        AddEntry(Surfaces, TEXT("TestRiver"), TEXT("拟合河网中心样条"), TEXT("fit_river_geometry"), TEXT("从选中河面提取分叉中心线。"));
        AddEntry(Surfaces, TEXT("TestArea"), TEXT("拟合地表 Area"), TEXT("fit_area_geometry"), TEXT("采样选中表面并创建纯几何区域。"));
        auto& Preview = Menu->AddSection(TEXT("Preview"));
        AddEntry(Preview, TEXT("ClearPreview"), TEXT("清除预览"), TEXT("clear_preview"), TEXT("清除 Room、门窗和地表预览，不删除已创建对象。"));
    }

    void PopulateViewFit(UToolMenu* Menu)
    {
        auto& Section = Menu->AddSection(TEXT("ViewFit"), FText::FromString(TEXT("从当前透视视口开始")));
        AddEntry(Section, TEXT("AcceptBoundaryCandidate"), TEXT("采纳所选 Room 候选…"), TEXT("accept_boundary_review"), TEXT("检查橙色边界后，仅为本候选确认超差。"));
        AddEntry(Section, TEXT("ViewRoom"), TEXT("拟合当前位置的 Room…"), TEXT("fit_view_room"), TEXT("飞入房间即可采样，预览后确认创建。"));
        AddEntry(Section, TEXT("ViewStair"), TEXT("探测当前位置的楼梯间…"), TEXT("fit_view_stair"), TEXT("将视口移至下平台，沿踏步寻找连通的平台。"));
        AddEntry(Section, TEXT("ViewFloor"), TEXT("制作当前位置的本层 Rooms 与门…"), TEXT("fit_view_floor"), TEXT("从视口所在房间向相邻门洞扩展，完成后审核 Portal。"));
    }

}

class FInteriorFitEditorModule : public IModuleInterface
{
public:
    void StartupModule() override
    {
        if (IsRunningCommandlet()) return;
        InteriorFitOpenings::Register();
        UToolMenus::RegisterStartupCallback(FSimpleMulticastDelegate::FDelegate::CreateRaw(this, &FInteriorFitEditorModule::RegisterMenus));
    }

    void ShutdownModule() override
    {
        if (IsRunningCommandlet()) return;
        UToolMenus::UnRegisterStartupCallback(this);
        UToolMenus::UnregisterOwner(this);
        InteriorFitOpenings::Shutdown();
    }

private:
    void RegisterMenus()
    {
        FToolMenuOwnerScoped Owner(this);
        auto& Tools = UToolMenus::Get()->ExtendMenu(TEXT("LevelEditor.MainMenu.Tools"))->FindOrAddSection(TEXT("InteriorFit"));
        Tools.AddSubMenu(TEXT("AudioAutoFitView"), FText::FromString(TEXT("Audio Auto Fit")),
            FText::FromString(TEXT("使用编辑器视口位置自动生成种子并开始拟合")), FNewToolMenuDelegate::CreateStatic(&PopulateViewFit));
        FToolMenuSection& Section = UToolMenus::Get()->ExtendMenu(TEXT("LevelEditor.ActorContextMenu"))->FindOrAddSection(TEXT("InteriorFit"));
        Section.AddSubMenu(TEXT("AudioAutoFit"), FText::FromString(TEXT("Audio Auto Fit")),
            FText::FromString(TEXT("房屋 Room / Portal 与地表几何制作")),
            FNewToolMenuDelegate::CreateStatic(&PopulateAudioAutoFit));
    }
};

IMPLEMENT_MODULE(FInteriorFitEditorModule, InteriorFitEditor)




