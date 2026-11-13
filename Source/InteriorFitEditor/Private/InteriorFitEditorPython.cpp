#include "InteriorFitEditorPython.h"

#include "IPythonScriptPlugin.h"
#include "Misc/MessageDialog.h"

#define LOCTEXT_NAMESPACE "InteriorFitEditorPython"

bool InteriorFitEditorPython::Execute(const FString& Command)
{
    IPythonScriptPlugin* Python = IPythonScriptPlugin::Get();
    if (!Python || !Python->IsPythonAvailable())
    {
        FMessageDialog::Open(EAppMsgType::Ok,
                             LOCTEXT("PythonUnavailable",
                                     "Interior Fit 需要 Python Editor Script Plugin。"
                                     "请启用插件并重启编辑器。"));
        return false;
    }
    if (!Python->ExecPythonCommand(*Command))
    {
        FMessageDialog::Open(
            EAppMsgType::Ok,
            LOCTEXT("PythonCommandFailed", "Interior Fit 无法完成操作。请查看输出日志。"));
        return false;
    }
    return true;
}

#undef LOCTEXT_NAMESPACE
