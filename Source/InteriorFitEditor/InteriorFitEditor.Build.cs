using UnrealBuildTool;

public class InteriorFitEditor : ModuleRules
{
    public InteriorFitEditor(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PublicDependencyModuleNames.AddRange(new[] { "Core", "CoreUObject", "Engine" });
        PrivateDependencyModuleNames.AddRange(new[] {
            "UnrealEd", "BSPUtils", "Slate", "SlateCore", "ToolMenus", "Projects", "PythonScriptPlugin", "Json",
            "GeometryCore", "GeometryFramework"
        });
    }
}

