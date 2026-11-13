#include "InteriorFitSurfaceSampleJSON.h"

#include "Serialization/JsonSerializer.h"

FString InteriorFitSurfaceSampleJSON::Encode(const TSharedRef<FJsonObject>& Data)
{
    FString JSON;
    FJsonSerializer::Serialize(Data, TJsonWriterFactory<>::Create(&JSON));
    return JSON;
}
FString InteriorFitSurfaceSampleJSON::Fail(const FString& Message)
{
    TSharedRef<FJsonObject> Data = MakeShared<FJsonObject>();
    Data->SetStringField(TEXT("error"), Message);
    return InteriorFitSurfaceSampleJSON::Encode(Data);
}
TArray<TSharedPtr<FJsonValue>> InteriorFitSurfaceSampleJSON::VectorJSON(const FVector& V)
{
    return {MakeShared<FJsonValueNumber>(V.X), MakeShared<FJsonValueNumber>(V.Y),
            MakeShared<FJsonValueNumber>(V.Z)};
}
