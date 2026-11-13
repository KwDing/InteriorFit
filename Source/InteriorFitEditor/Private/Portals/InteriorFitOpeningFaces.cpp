#include "InteriorFitOpeningFaces.h"

#include "Dom/JsonObject.h"
#include "Engine/Polys.h"
#include "GameFramework/Volume.h"
#include "Model.h"
#include "Surfaces/InteriorFitSurfaceSampleJSON.h"
#include "Serialization/JsonSerializer.h"

namespace
{
    constexpr double MaxVerticalNormalZ = 0.15;
    constexpr double PanelSidePaddingCm = 60;
    constexpr double PanelHeightPaddingCm = 30;
} // namespace

FString InteriorFitOpeningFaces::GetVolumeFaces(AVolume* Volume)
{
    TArray<TSharedPtr<FJsonValue>> Faces;
    if (!IsInGameThread() || !IsValid(Volume) || !Volume->Brush || !Volume->Brush->Polys)
    {
        return TEXT("[]");
    }
    const FTransform Transform = Volume->GetActorTransform();
    for (const FPoly& Poly : Volume->Brush->Polys->Element)
    {
        if (Poly.Vertices.Num() < 3)
        {
            continue;
        }
        const FVector First = Transform.TransformPosition(FVector(Poly.Vertices[0]));
        const FVector Second = Transform.TransformPosition(FVector(Poly.Vertices[1]));
        const FVector Third = Transform.TransformPosition(FVector(Poly.Vertices[2]));
        const FVector Normal = FVector::CrossProduct(Second - First, Third - First).GetSafeNormal();
        if (Normal.IsNearlyZero() || FMath::Abs(Normal.Z) > MaxVerticalNormalZ)
        {
            continue;
        }
        TSharedPtr<FJsonObject> Face = MakeShared<FJsonObject>();
        Face->SetArrayField(TEXT("normal"), InteriorFitSurfaceSampleJSON::VectorJSON(Normal));
        TArray<TSharedPtr<FJsonValue>> Vertices;
        for (const FVector3f& Vertex : Poly.Vertices)
        {
            Vertices.Add(MakeShared<FJsonValueArray>(InteriorFitSurfaceSampleJSON::VectorJSON(
                Transform.TransformPosition(FVector(Vertex)))));
        }
        Face->SetArrayField(TEXT("vertices"), Vertices);
        Faces.Add(MakeShared<FJsonValueObject>(Face));
    }
    FString JSON;
    FJsonSerializer::Serialize(Faces, TJsonWriterFactory<>::Create(&JSON));
    return JSON;
}

FString InteriorFitOpeningFaces::GetActorPanelFace(AActor* Actor)
{
    if (!IsInGameThread() || !IsValid(Actor))
    {
        return TEXT("[]");
    }
    const FBox Box = Actor->CalculateComponentsBoundingBoxInLocalSpace(true);
    if (!Box.IsValid)
    {
        return TEXT("[]");
    }
    const FVector Center = Box.GetCenter();
    const FVector Extent = Box.GetExtent();
    const bool bAlongX = Extent.X < Extent.Y;
    const FVector Across = bAlongX ? FVector(0, Extent.Y + PanelSidePaddingCm, 0)
                                   : FVector(Extent.X + PanelSidePaddingCm, 0, 0);
    const FVector Up(0, 0, Extent.Z + PanelHeightPaddingCm);
    const FTransform Transform = Actor->GetActorTransform();
    const FVector Normal =
        Transform.TransformVectorNoScale(bAlongX ? FVector::ForwardVector : FVector::RightVector)
            .GetSafeNormal();
    TSharedPtr<FJsonObject> Face = MakeShared<FJsonObject>();
    Face->SetArrayField(TEXT("normal"), InteriorFitSurfaceSampleJSON::VectorJSON(Normal));
    TArray<TSharedPtr<FJsonValue>> Vertices;
    for (const FVector& Point :
         {Center - Across - Up, Center + Across - Up, Center + Across + Up, Center - Across + Up})
    {
        Vertices.Add(MakeShared<FJsonValueArray>(
            InteriorFitSurfaceSampleJSON::VectorJSON(Transform.TransformPosition(Point))));
    }
    Face->SetArrayField(TEXT("vertices"), Vertices);
    FString JSON;
    FJsonSerializer::Serialize(TArray<TSharedPtr<FJsonValue>>{MakeShared<FJsonValueObject>(Face)},
                               TJsonWriterFactory<>::Create(&JSON));
    return JSON;
}
