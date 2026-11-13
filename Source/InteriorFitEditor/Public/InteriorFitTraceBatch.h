#pragma once

#include "CoreMinimal.h"
#include "Containers/Ticker.h"
#include "Engine/World.h"
#include "InteriorFitTraceBatch.generated.h"

/** Ordered world-space ray endpoints in centimeters and an optional immediate time budget. */
USTRUCT(BlueprintType)
struct FInteriorFitTraceRequest
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Interior Fit")
    TArray<FVector> Starts;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Interior Fit")
    TArray<FVector> Ends;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Interior Fit")
    TArray<AActor*> Ignored;

    UPROPERTY(EditAnywhere, BlueprintReadWrite, Category = "Interior Fit", meta = (Units = "ms"))
    float ImmediateBudgetMs = 0.0f;
};

/** Results retain request order. A non-blocking FHitResult represents a miss. */
UCLASS(BlueprintType)
class INTERIORFITEDITOR_API UInteriorFitTraceBatch : public UObject
{
    GENERATED_BODY()
  public:
    /** Submit ordered centimeter rays in the editor world on the game thread. */
    UFUNCTION(BlueprintCallable, Category = "Interior Fit")
    static UInteriorFitTraceBatch* SubmitRequest(AActor* Seed,
                                                 const FInteriorFitTraceRequest& Request);

    /** Compatibility entry point for existing Blueprint and Python callers. */
    UFUNCTION(BlueprintCallable, Category = "Interior Fit",
              meta = (DeprecatedFunction, DeprecationMessage = "Use Submit Request."))
    static UInteriorFitTraceBatch* Submit(AActor* Seed, const TArray<FVector>& Starts,
                                          const TArray<FVector>& Ends,
                                          const TArray<AActor*>& Ignored,
                                          float ImmediateBudgetMs = 0.0f);

    /** Game-thread cancellation; late weak-bound async callbacks are ignored. */
    UFUNCTION(BlueprintCallable, Category = "Interior Fit")
    void Cancel();

    UPROPERTY(BlueprintReadOnly, Category = "Interior Fit")
    TArray<FHitResult> Hits;

    UPROPERTY(BlueprintReadOnly, Category = "Interior Fit")
    int32 Pending = 0;

    UPROPERTY(BlueprintReadOnly, Category = "Interior Fit")
    bool bFrameSliced = false;

  protected:
    virtual void BeginDestroy() override;

  private:
    void PreActorTick(UWorld* World, ELevelTick TickType, float Delta);
    bool Pump(float Delta);
    void TraceSlice(UWorld* World, double EndTime);
    void OnTrace(const FTraceHandle& Handle, FTraceDatum& Datum);

    TWeakObjectPtr<UWorld> TargetWorld;
    TArray<FVector> RayStarts;
    TArray<FVector> RayEnds;
    FCollisionQueryParams Query;
    FDelegateHandle PreTickHandle;
    FTSTicker::FDelegateHandle PumpHandle;
    uint64 QueuedFrame = 0;
    double Deadline = 0;
    bool bSubmitted = false;
    bool bCancelled = false;
    int32 NextRay = 0;
};
