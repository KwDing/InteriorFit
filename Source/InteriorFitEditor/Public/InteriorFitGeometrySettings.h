#pragma once
#include "CoreMinimal.h"
#include "UObject/Object.h"
#include "InteriorFitGeometrySettings.generated.h"

/** Fixed by the menu command; controls which draft properties are relevant. */
UENUM(BlueprintType)
enum class EInteriorFitGeometryMethod : uint8
{
    Lake,
    River,
    Area
};

/** Editor-owned modal draft for geometry only; no Event or host Audio Manager. */
UCLASS(BlueprintType)
class INTERIORFITEDITOR_API UInteriorFitGeometrySettings : public UObject
{
    GENERATED_BODY()
public:
    // Not editable in Details: changing the draft must not switch the menu operation.
    UPROPERTY(BlueprintReadWrite, Category="几何拟合")
    EInteriorFitGeometryMethod Method = EInteriorFitGeometryMethod::Lake;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="样条简化",
        meta=(ClampMin="0", ClampMax="1000", Units="cm", DisplayName="简化容差",
              EditCondition="Method != EInteriorFitGeometryMethod::Area", EditConditionHides))
    float SimplificationToleranceCM = 20;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="样条简化",
        meta=(ClampMin="3", ClampMax="256", DisplayName="每条样条最多控制点",
              EditCondition="Method != EInteriorFitGeometryMethod::Area", EditConditionHides))
    int32 MaximumPoints = 128;

    // Match SampleAreaSurface's existing minimum; smaller input is not supported.
    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category="表面采样",
        meta=(ClampMin="25", ClampMax="500", Units="cm", DisplayName="采样格大小",
              ToolTip="河流：提取分叉中心线的河面采样间距。Area：记录起伏地表的采样间距。更小的格子增加采样量。",
              EditCondition="Method != EInteriorFitGeometryMethod::Lake", EditConditionHides))
    float CellSizeCM = 40;
};
