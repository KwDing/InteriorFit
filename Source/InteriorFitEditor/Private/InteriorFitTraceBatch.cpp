#include "InteriorFitTraceBatch.h"
#include "GameFramework/Actor.h"
#include "HAL/PlatformTime.h"

namespace
{
    // Game-thread only. Recheck periodically in case this editor world resumes actor ticks.
    TWeakObjectPtr<UWorld> RecentlyTimeOnlyWorld;
    double RecheckActorTicksAt = 0;
    constexpr double MaximumImmediateSeconds = 0.00075;
}

UInteriorFitTraceBatch* UInteriorFitTraceBatch::Submit(AActor* Seed, const TArray<FVector>& Starts,
    const TArray<FVector>& Ends, const TArray<AActor*>& Ignored, float ImmediateBudgetMs)
{
    UWorld* World = IsValid(Seed) ? Seed->GetWorld() : nullptr;
    if (!IsInGameThread() || !World || World->WorldType != EWorldType::Editor ||
        Starts.Num() != Ends.Num() || Starts.IsEmpty() || Starts.Num() > 128)
        return nullptr;

    auto* Batch = NewObject<UInteriorFitTraceBatch>();
    Batch->Hits.SetNum(Starts.Num());
    Batch->Pending = Starts.Num();
    Batch->TargetWorld = World;
    Batch->RayStarts = Starts;
    Batch->RayEnds = Ends;
    Batch->Query = FCollisionQueryParams(SCENE_QUERY_STAT(InteriorFitContour), true, Seed);
    Batch->Query.AddIgnoredActors(Ignored);
    Batch->QueuedFrame = GFrameCounter;
    const double Now = FPlatformTime::Seconds();
    if (ImmediateBudgetMs > 0 && RecentlyTimeOnlyWorld.Get() == World && Now < RecheckActorTicksAt)
    {
        // Opt-in only: the original four-argument call retains deferred dispatch.
        // Python shares its remaining callback budget, not a fresh budget per wave.
        Batch->bFrameSliced = true;
        Batch->TraceSlice(World, Now + FMath::Min(ImmediateBudgetMs * 0.001, MaximumImmediateSeconds));
    }
    if (!Batch->Pending) return Batch;
    if (!Batch->bFrameSliced)
        Batch->PreTickHandle = FWorldDelegates::OnWorldPreActorTick.AddUObject(Batch, &UInteriorFitTraceBatch::PreActorTick);
    Batch->PumpHandle = FTSTicker::GetCoreTicker().AddTicker(FTickerDelegate::CreateUObject(Batch, &UInteriorFitTraceBatch::Pump));
    return Batch;
}

void UInteriorFitTraceBatch::Cancel()
{
    check(IsInGameThread());
    bCancelled = true;
    Pending = 0;
    FWorldDelegates::OnWorldPreActorTick.Remove(PreTickHandle);
    PreTickHandle.Reset();
    FTSTicker::RemoveTicker(PumpHandle);
    PumpHandle.Reset();
}

void UInteriorFitTraceBatch::PreActorTick(UWorld* World, ELevelTick, float)
{
    if (World != TargetWorld.Get() || bSubmitted || bFrameSliced || bCancelled) return;
    if (RecentlyTimeOnlyWorld.Get() == World) RecentlyTimeOnlyWorld.Reset();
    bSubmitted = true;
    Deadline = FPlatformTime::Seconds() + 1.0;
    FTraceDelegate Delegate = FTraceDelegate::CreateUObject(this, &UInteriorFitTraceBatch::OnTrace);
    for (int32 Index = 0; Index < RayStarts.Num(); ++Index)
        World->AsyncLineTraceByChannel(EAsyncTraceType::Single, RayStarts[Index], RayEnds[Index],
            ECC_Pawn, Query, FCollisionResponseParams::DefaultResponseParam, &Delegate, Index);
}

bool UInteriorFitTraceBatch::Pump(float)
{
    UWorld* World = TargetWorld.Get();
    if (!World || !Pending)
    {
        FWorldDelegates::OnWorldPreActorTick.Remove(PreTickHandle);
        PreTickHandle.Reset();
        PumpHandle.Reset(); // Returning false removes this executing ticker.
        return false;
    }
    // Give the target world one complete frame to dispatch actor ticks. A fixed
    // delay here accumulates on every dependent wave of a large flood scan.
    const double Now = FPlatformTime::Seconds();
    const bool bKnownTimeOnly = RecentlyTimeOnlyWorld.Get() == World && Now < RecheckActorTicksAt;
    if (!bFrameSliced && !bSubmitted && !bKnownTimeOnly)
    {
        if (GFrameCounter <= QueuedFrame + 1) return true;
        RecentlyTimeOnlyWorld = World;
        RecheckActorTicksAt = Now + 0.35;
    }
    if (bSubmitted && Now < Deadline) return true;

    // Non-realtime editor worlds skip the actor ticks that deliver async trace results.
    // Replay the same rays with a small wall-time budget rather than ticking physics manually.
    bFrameSliced = true;
    TraceSlice(World, FPlatformTime::Seconds() + 0.0015);
    return true;
}

void UInteriorFitTraceBatch::TraceSlice(UWorld* World, double EndTime)
{
    do
    {
        FHitResult Hit;
        World->LineTraceSingleByChannel(Hit, RayStarts[NextRay], RayEnds[NextRay], ECC_Pawn, Query);
        Hits[NextRay++] = Hit;
    }
    while (NextRay < Hits.Num() && FPlatformTime::Seconds() < EndTime);
    Pending = Hits.Num() - NextRay;
}

void UInteriorFitTraceBatch::OnTrace(const FTraceHandle&, FTraceDatum& Datum)
{
    if (bFrameSliced || bCancelled) return;
    if (!Datum.OutHits.IsEmpty()) Hits[Datum.UserData] = Datum.OutHits[0];
    --Pending;
}

void UInteriorFitTraceBatch::BeginDestroy()
{
    Cancel();
    Super::BeginDestroy();
}
