"""Compatibility facade that registers and exports every SQLAlchemy model."""

from telegram_lead_discovery.storage.model_parts.base import Base, utcnow

from telegram_lead_discovery.storage.model_parts.administration import (
    OperatorSetting,
    SettingChange,
    Job,
    NotificationOutbox,
    NotificationDelivery,
    ComponentHealth,
    MetricBucket,
    AdminAction,
)

from telegram_lead_discovery.storage.model_parts.sources import (
    TelegramSource,
    SourceAlias,
    SourceApprovalEvent,
    KeywordDiscoveryProfile,
    KeywordDiscoveryProfileVersion,
)

from telegram_lead_discovery.storage.model_parts.discovery import (
    DiscoveryRun,
    DiscoveryRunQuery,
    SourceDiscoveryEvidence,
    SourceOpportunitySnapshot,
    DiscoveryTerminalOutcome,
)

from telegram_lead_discovery.storage.model_parts.suppression import (
    DismissedKeywordSource,
    PresentedKeywordSource,
    DismissSuppressReconsideredEvent,
    SourceDiscoveryEvent,
)

from telegram_lead_discovery.storage.model_parts.collector import (
    TelegramAccount,
    CollectorCheckpoint,
    TelegramEventEnvelope,
    TelegramAuthor,
    TelegramMessage,
    TelegramMessageRevision,
    DuplicateGroup,
    MessageDuplicate,
)

from telegram_lead_discovery.storage.model_parts.processing import (
    RuleSetVersion,
    ServiceProfile,
    KeywordGroup,
    MonitoringRule,
    DetectionResult,
    ProcessingRun,
    ProcessingResult,
    ProcessingLog,
)

from telegram_lead_discovery.storage.model_parts.leads import (
    Lead,
    LeadScore,
    LeadScoreComponent,
    LeadStatusHistory,
    LeadFeedback,
    DeletionTombstone,
    BackupManifest,
)
