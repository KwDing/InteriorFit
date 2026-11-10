#include "InteriorFitOpeningsPanel.h"

#include "Dom/JsonObject.h"
#include "Editor.h"
#include "Framework/Docking/TabManager.h"
#include "InteriorFitLibrary.h"
#include "IPythonScriptPlugin.h"
#include "Misc/Base64.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Widgets/Docking/SDockTab.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Input/SCheckBox.h"
#include "Widgets/Input/SEditableTextBox.h"
#include "Widgets/Layout/SScrollBox.h"
#include "Widgets/SBoxPanel.h"
#include "Widgets/SCompoundWidget.h"
#include "Widgets/SNullWidget.h"
#include "Widgets/Text/STextBlock.h"

namespace InteriorFitOpenings
{
    static const FName TabID(TEXT("InteriorFitOpenings"));
    static TWeakPtr<SDockTab> CurrentTab;

    static void Clear()
    {
        if (GEditor) UInteriorFitLibrary::DrawOpeningPreviews(GEditor->GetEditorWorldContext().World(), TEXT("[]"));
    }

    class SOpeningList : public SCompoundWidget
    {
    public:
        SLATE_BEGIN_ARGS(SOpeningList) {} SLATE_END_ARGS()

        void Construct(const FArguments&, TSharedPtr<FJsonObject> InData)
        {
            Data = InData;
            TSharedRef<SVerticalBox> Body = SNew(SVerticalBox);
            Body->AddSlot().AutoHeight().Padding(8)[SNew(STextBlock).AutoWrapText(true).Text(FText::FromString(
                TEXT("Include selects a row for preview/creation. Open state only controls sound transmission. All rows can be previewed; Create skips blocked/existing rows. Orange = closed. Preview creates no Actors.")))];
            TSharedRef<SHorizontalBox> Buttons = SNew(SHorizontalBox);
            Buttons->AddSlot().AutoWidth().Padding(4)[SNew(SButton).Text(FText::FromString(TEXT("Select all"))).OnClicked(this, &SOpeningList::SelectAll)];
            Buttons->AddSlot().AutoWidth().Padding(4)[SNew(SButton).Text(FText::FromString(TEXT("Select available"))).OnClicked(this, &SOpeningList::SelectAvailable)];
            Buttons->AddSlot().AutoWidth().Padding(4)[SNew(SButton).Text(FText::FromString(TEXT("Select none"))).OnClicked(this, &SOpeningList::SelectNone)];
            Buttons->AddSlot().AutoWidth().Padding(4)[SNew(SButton).Text(FText::FromString(TEXT("Preview checked"))).OnClicked(this, &SOpeningList::Preview)];
            Buttons->AddSlot().AutoWidth().Padding(4)[SNew(SButton).Text(FText::FromString(TEXT("Create checked"))).OnClicked(this, &SOpeningList::Create)];
            Buttons->AddSlot().AutoWidth().Padding(4)[SNew(SButton).Text(FText::FromString(TEXT("Clear preview"))).OnClicked_Lambda([] { Clear(); return FReply::Handled(); })];
            Body->AddSlot().AutoHeight()[Buttons];
            Body->AddSlot().AutoHeight().Padding(8)[SNew(STextBlock).Text(this, &SOpeningList::SelectionSummary)];
            TSharedRef<SScrollBox> Scroll = SNew(SScrollBox);
            for (const TSharedPtr<FJsonValue>& Value : Data->GetArrayField(TEXT("rows")))
            {
                TSharedPtr<FJsonObject> Row = Value->AsObject();
                Rows.Add(Row);
                Scroll->AddSlot().Padding(4)[MakeRow(Row)];
            }
            Body->AddSlot().FillHeight(1.0f)[Scroll];
            ChildSlot[Body];
        }

    private:
        TSharedRef<SWidget> MakeRow(TSharedPtr<FJsonObject> Row)
        {
            TSharedRef<SVerticalBox> Cell = SNew(SVerticalBox);
            Cell->AddSlot().AutoHeight()[SNew(SHorizontalBox)
                + SHorizontalBox::Slot().AutoWidth().Padding(4)[SNew(SCheckBox)
                    .IsChecked_Lambda([Row] { return Row->GetBoolField(TEXT("checked")) ? ECheckBoxState::Checked : ECheckBoxState::Unchecked; })
                    .OnCheckStateChanged_Lambda([Row](ECheckBoxState State) { Row->SetBoolField(TEXT("checked"), State == ECheckBoxState::Checked); })
                    [SNew(STextBlock).Text(FText::FromString(TEXT("Include")))]]
                + SHorizontalBox::Slot().FillWidth(1)[SNew(SEditableTextBox).Text(FText::FromString(Row->GetStringField(TEXT("name"))))
                    .OnTextChanged_Lambda([Row](const FText& Text) { Row->SetStringField(TEXT("name"), Text.ToString()); })]
                + SHorizontalBox::Slot().AutoWidth().Padding(4)[SNew(SCheckBox)
                    .IsChecked_Lambda([Row] { return Row->GetBoolField(TEXT("open")) ? ECheckBoxState::Checked : ECheckBoxState::Unchecked; })
                    .OnCheckStateChanged_Lambda([Row](ECheckBoxState State) { Row->SetBoolField(TEXT("open"), State == ECheckBoxState::Checked); })
                    [SNew(STextBlock).Text(FText::FromString(TEXT("Open state")))]]
                + SHorizontalBox::Slot().AutoWidth().Padding(4)[SNew(SButton).Text(FText::FromString(TEXT("Preview this")))
                    .OnClicked(this, &SOpeningList::PreviewOne, Row)]];
            Cell->AddSlot().AutoHeight().Padding(28, 2)[SNew(STextBlock).AutoWrapText(true).Text(FText::FromString(Row->GetStringField(TEXT("summary"))))];
            return Cell;
        }

        FReply Dispatch(const TCHAR* Action, TSharedPtr<FJsonObject> Single = nullptr)
        {
            TSharedPtr<FJsonObject> Payload = MakeShared<FJsonObject>();
            Payload->SetStringField(TEXT("world"), Data->GetStringField(TEXT("world")));
            TArray<TSharedPtr<FJsonValue>> Chosen;
            for (const TSharedPtr<FJsonObject>& Row : Rows)
                if (Single.IsValid() ? Row == Single : Row->GetBoolField(TEXT("checked")))
                    if (FCString::Strcmp(Action, TEXT("create")) != 0 || !Row->GetBoolField(TEXT("blocked")))
                        Chosen.Add(MakeShared<FJsonValueObject>(Row));
            Payload->SetArrayField(TEXT("rows"), Chosen);
            FString JSON;
            FJsonSerializer::Serialize(Payload.ToSharedRef(), TJsonWriterFactory<>::Create(&JSON));
            if (IPythonScriptPlugin* Python = IPythonScriptPlugin::Get())
            {
                const FString Command = FString::Printf(TEXT("import json,base64; from interior_fit import openings; openings.apply_action('%s',json.loads(base64.b64decode('%s').decode('utf-8')))"), Action, *FBase64::Encode(JSON));
                Python->ExecPythonCommand(*Command);
            }
            return FReply::Handled();
        }

        FReply Preview() { return Dispatch(TEXT("preview")); }
        FReply PreviewOne(TSharedPtr<FJsonObject> Row) { return Dispatch(TEXT("focus"), Row); }
        FReply Create() { return Dispatch(TEXT("create")); }
        FText SelectionSummary() const
        {
            int32 Included = 0;
            int32 Creatable = 0;
            for (const auto& Row : Rows)
                if (Row->GetBoolField(TEXT("checked")))
                {
                    ++Included;
                    if (!Row->GetBoolField(TEXT("blocked"))) ++Creatable;
                }
            return FText::FromString(FString::Printf(TEXT("Preview: %d / %d boxes | Create: %d | Blocked/existing skipped for creation: %d"), Included, Rows.Num(), Creatable, Included - Creatable));
        }

        FReply SelectAll() { for (const auto& Row : Rows) Row->SetBoolField(TEXT("checked"), true); return FReply::Handled(); }
        FReply SelectAvailable() { for (const auto& Row : Rows) Row->SetBoolField(TEXT("checked"), !Row->GetBoolField(TEXT("blocked"))); return FReply::Handled(); }
        FReply SelectNone() { for (const auto& Row : Rows) Row->SetBoolField(TEXT("checked"), false); return FReply::Handled(); }

        TSharedPtr<FJsonObject> Data;
        TArray<TSharedPtr<FJsonObject>> Rows;
    };

    void Register()
    {
        FGlobalTabmanager::Get()->RegisterNomadTabSpawner(TabID, FOnSpawnTab::CreateLambda([](const FSpawnTabArgs&)
        {
            TSharedRef<SDockTab> Tab = SNew(SDockTab).TabRole(ETabRole::NomadTab);
            Tab->SetOnTabClosed(SDockTab::FOnTabClosedCallback::CreateLambda([](TSharedRef<SDockTab>) { Clear(); }));
            CurrentTab = Tab;
            return Tab;
        })).SetDisplayName(FText::FromString(TEXT("Interior Fit — Openings"))).SetMenuType(ETabSpawnerMenuType::Hidden);
    }

    bool Show(const FString& JSON)
    {
        TSharedPtr<FJsonObject> Data;
        if (!FJsonSerializer::Deserialize(TJsonReaderFactory<>::Create(JSON), Data) || !Data.IsValid()) return false;
        const TArray<TSharedPtr<FJsonValue>>* Rows = nullptr;
        if (!Data->HasTypedField<EJson::String>(TEXT("world")) || !Data->TryGetArrayField(TEXT("rows"), Rows) || Rows->Num() > 128) return false;
        for (const TSharedPtr<FJsonValue>& Value : *Rows)
        {
            if (!Value.IsValid() || Value->Type != EJson::Object) return false;
            const TSharedPtr<FJsonObject> Row = Value->AsObject();
            if (!Row.IsValid() || !Row->HasTypedField<EJson::String>(TEXT("name")) ||
                !Row->HasTypedField<EJson::String>(TEXT("summary")) ||
                !Row->HasTypedField<EJson::Boolean>(TEXT("blocked")) ||
                !Row->HasTypedField<EJson::Boolean>(TEXT("checked")) ||
                !Row->HasTypedField<EJson::Boolean>(TEXT("open"))) return false;
        }
        TSharedPtr<SDockTab> Tab = FGlobalTabmanager::Get()->TryInvokeTab(TabID);
        if (!Tab.IsValid()) return false;
        Tab->SetContent(SNew(SOpeningList, Data));
        return true;
    }

    void Shutdown()
    {
        Clear();
        if (TSharedPtr<SDockTab> Tab = CurrentTab.Pin())
        {
            Tab->SetOnTabClosed(SDockTab::FOnTabClosedCallback());
            Tab->SetContent(SNullWidget::NullWidget);
            Tab->RequestCloseTab();
        }
        CurrentTab.Reset();
        FGlobalTabmanager::Get()->UnregisterNomadTabSpawner(TabID);
    }
}
