"""
TelegramCapabilityRegistry
==========================

Every Bot API capability is registered here with its status, minimum
required API version, permissions needed, and fallback behaviour.

Architecture:

    TelegramCapabilityRegistry
    ├── OfficialCapabilities     (fully documented, implemented)
    ├── VersionedCapabilities    (available only from a certain API version)
    ├── ExperimentalCapabilities (behind a feature flag)
    ├── FutureCapabilities       (adapter only, not yet released)
    └── UnsupportedCapabilities  (confirmed unavailable — with fallback)

When Telegram ships a new Bot API version:
  1. Add the new capability here.
  2. Set min_bot_api_version.
  3. Enable the feature flag if needed.
  4. Add integration tests.
  5. Never break existing installations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from app.core.logging_config import get_logger

log = get_logger(__name__)


class CapabilityStatus(str, Enum):
    OFFICIAL = "official"           # Fully documented and stable
    VERSIONED = "versioned"         # Available from min_bot_api_version
    EXPERIMENTAL = "experimental"   # Behind feature flag
    FUTURE = "future"               # Adapter placeholder for unreleased feature
    UNSUPPORTED = "unsupported"     # Confirmed unavailable — fallback only


class CapabilityAvailability(str, Enum):
    ALL_CHATS = "all_chats"
    CHANNELS_ONLY = "channels_only"
    GROUPS_ONLY = "groups_only"
    SUPERGROUPS_ONLY = "supergroups_only"
    PRIVATE_ONLY = "private_only"
    ADMIN_REQUIRED = "admin_required"
    CONDITIONAL = "conditional"


@dataclass
class TelegramCapability:
    name: str
    telegram_method: str
    status: CapabilityStatus
    availability: CapabilityAvailability = CapabilityAvailability.ALL_CHATS
    min_bot_api_version: str = "6.0"   # Minimum stable API version we support
    permissions_required: list[str] = field(default_factory=list)
    fallback: str | None = None
    documentation_url: str = "https://core.telegram.org/bots/api"
    implemented: bool = True
    notes: str = ""
    _adapter: Callable | None = field(default=None, init=False, repr=False)

    @property
    def is_available(self) -> bool:
        return self.status in (CapabilityStatus.OFFICIAL, CapabilityStatus.VERSIONED)


class TelegramCapabilityRegistry:
    """
    Central registry for all Telegram Bot API capabilities.

    Usage:
        registry = TelegramCapabilityRegistry()
        cap = registry.get("send_message")
        if cap.is_available:
            ...
    """

    def __init__(self, current_api_version: str = "10.3") -> None:
        self.current_api_version = current_api_version
        self._capabilities: dict[str, TelegramCapability] = {}
        self._populate()

    def register(self, cap: TelegramCapability) -> None:
        self._capabilities[cap.name] = cap
        log.debug("capability_registered", name=cap.name, status=cap.status)

    def get(self, name: str) -> TelegramCapability:
        cap = self._capabilities.get(name)
        if cap is None:
            raise KeyError(f"Unknown capability: '{name}'")
        return cap

    def is_available(self, name: str) -> bool:
        cap = self._capabilities.get(name)
        if cap is None:
            return False
        if cap.status in (CapabilityStatus.FUTURE, CapabilityStatus.UNSUPPORTED):
            return False
        if cap.status == CapabilityStatus.VERSIONED:
            return self._version_gte(self.current_api_version, cap.min_bot_api_version)
        return True

    def get_fallback(self, name: str) -> str | None:
        cap = self._capabilities.get(name)
        return cap.fallback if cap else None

    def matrix(self) -> list[dict[str, Any]]:
        """Return the full capability matrix for the dashboard / docs."""
        rows = []
        for cap in self._capabilities.values():
            rows.append({
                "capability": cap.name,
                "method": cap.telegram_method,
                "available": self.is_available(cap.name),
                "implemented": cap.implemented,
                "status": cap.status.value,
                "min_api_version": cap.min_bot_api_version,
                "fallback": cap.fallback or "—",
                "permissions": cap.permissions_required,
                "notes": cap.notes,
                "docs": cap.documentation_url,
            })
        return sorted(rows, key=lambda r: r["capability"])

    @staticmethod
    def _version_gte(current: str, required: str) -> bool:
        def v(s: str) -> tuple[int, ...]:
            return tuple(int(x) for x in s.split("."))
        return v(current) >= v(required)

    # ──────────────────────────────────────────────────────────
    # Capability definitions — verified against Bot API 10.3
    # ──────────────────────────────────────────────────────────

    def _populate(self) -> None:  # noqa: C901
        _O = CapabilityStatus.OFFICIAL
        _V = CapabilityStatus.VERSIONED
        _E = CapabilityStatus.EXPERIMENTAL
        _F = CapabilityStatus.FUTURE
        _U = CapabilityStatus.UNSUPPORTED

        _A = CapabilityAvailability
        docs = "https://core.telegram.org/bots/api"

        caps: list[TelegramCapability] = [

            # ── Messaging ─────────────────────────────────────
            TelegramCapability("send_message", "sendMessage", _O,
                notes="Core text message. Supports HTML/MarkdownV2/entities.",
                documentation_url=f"{docs}#sendmessage"),
            TelegramCapability("edit_message_text", "editMessageText", _O,
                documentation_url=f"{docs}#editmessagetext"),
            TelegramCapability("delete_message", "deleteMessage", _O,
                documentation_url=f"{docs}#deletemessage"),
            TelegramCapability("copy_message", "copyMessage", _O,
                documentation_url=f"{docs}#copymessage"),
            TelegramCapability("forward_message", "forwardMessage", _O,
                availability=_A.CONDITIONAL,
                notes="Requires has_protected_content=false on source.",
                documentation_url=f"{docs}#forwardmessage"),
            TelegramCapability("pin_message", "pinChatMessage", _O,
                availability=_A.ADMIN_REQUIRED,
                permissions_required=["can_pin_messages"],
                documentation_url=f"{docs}#pinchatmessage"),
            TelegramCapability("unpin_message", "unpinChatMessage", _O,
                availability=_A.ADMIN_REQUIRED,
                permissions_required=["can_pin_messages"],
                documentation_url=f"{docs}#unpinchatmessage"),

            # ── Media ─────────────────────────────────────────
            TelegramCapability("send_photo", "sendPhoto", _O,
                documentation_url=f"{docs}#sendphoto"),
            TelegramCapability("send_video", "sendVideo", _O,
                documentation_url=f"{docs}#sendvideo"),
            TelegramCapability("send_audio", "sendAudio", _O,
                documentation_url=f"{docs}#sendaudio"),
            TelegramCapability("send_document", "sendDocument", _O,
                documentation_url=f"{docs}#senddocument"),
            TelegramCapability("send_voice", "sendVoice", _O,
                documentation_url=f"{docs}#sendvoice"),
            TelegramCapability("send_video_note", "sendVideoNote", _O,
                documentation_url=f"{docs}#sendvideonote"),
            TelegramCapability("send_animation", "sendAnimation", _O,
                documentation_url=f"{docs}#sendanimation"),
            TelegramCapability("send_sticker", "sendSticker", _O,
                documentation_url=f"{docs}#sendsticker"),
            TelegramCapability("send_media_group", "sendMediaGroup", _O,
                notes="Up to 10 items per group. Media must be consistent type.",
                documentation_url=f"{docs}#sendmediagroup"),
            TelegramCapability("edit_message_media", "editMessageMedia", _O,
                documentation_url=f"{docs}#editmessagemedia"),

            # ── Live Photo (Bot API 10.0) ─────────────────────
            TelegramCapability("send_live_photo", "sendLivePhoto", _V,
                min_bot_api_version="10.0",
                documentation_url=f"{docs}#sendlivephoto"),

            # ── Rich Messages (Bot API 10.1) ──────────────────
            TelegramCapability("send_rich_message", "sendRichMessage", _V,
                min_bot_api_version="10.1",
                notes="Structured content: paragraphs, tables, collages, slideshows, thinking blocks.",
                documentation_url=f"{docs}#sendrichmessage"),
            TelegramCapability("send_rich_message_draft", "sendRichMessageDraft", _V,
                min_bot_api_version="10.1",
                notes="Stream partial rich messages for AI-generated content.",
                documentation_url=f"{docs}#sendrichmessagedraft"),
            TelegramCapability("edit_message_rich", "editMessageText", _V,
                min_bot_api_version="10.1",
                notes="Pass rich_message parameter to editMessageText.",
                documentation_url=f"{docs}#editmessagetext"),

            # ── Ephemeral Messages (Bot API 10.2) ─────────────
            TelegramCapability("send_ephemeral_message", "sendMessage+ephemeral_message_parameters", _V,
                min_bot_api_version="10.2",
                availability=_A.GROUPS_ONLY,
                notes="Messages visible only to a specific user. Requires receiver_user_id.",
                documentation_url=f"{docs}#ephemeralmessages"),
            TelegramCapability("edit_ephemeral_message_text", "editEphemeralMessageText", _V,
                min_bot_api_version="10.2",
                documentation_url=f"{docs}#editephemeralmessagetext"),
            TelegramCapability("delete_ephemeral_message", "deleteEphemeralMessage", _V,
                min_bot_api_version="10.2",
                documentation_url=f"{docs}#deleteephemeralmessage"),

            # ── Rich Message Buttons (Bot API 10.3) ───────────
            TelegramCapability("rich_message_buttons", "sendRichMessage+buttons", _V,
                min_bot_api_version="10.3",
                documentation_url=f"{docs}#richmessagebutton"),
            TelegramCapability("disabled_buttons", "InlineKeyboardButton+disabled", _V,
                min_bot_api_version="10.3",
                notes="Grey-out buttons while content loads or action is unavailable.",
                documentation_url=f"{docs}#disabledbutton"),
            TelegramCapability("expandable_quote_block", "InputRichBlockExpandableBlockQuotation", _V,
                min_bot_api_version="10.3",
                documentation_url=f"{docs}#inputrichblockexpandableblockquotation"),

            # ── Keyboards & Buttons ───────────────────────────
            TelegramCapability("inline_keyboard", "InlineKeyboardMarkup", _O,
                documentation_url=f"{docs}#inlinekeyboardmarkup"),
            TelegramCapability("reply_keyboard", "ReplyKeyboardMarkup", _O,
                documentation_url=f"{docs}#replykeyboardmarkup"),
            TelegramCapability("keyboard_button_url", "InlineKeyboardButton.url", _O,
                documentation_url=f"{docs}#inlinekeyboardbutton"),
            TelegramCapability("keyboard_button_callback", "InlineKeyboardButton.callback_data", _O,
                documentation_url=f"{docs}#inlinekeyboardbutton"),
            TelegramCapability("keyboard_button_web_app", "InlineKeyboardButton.web_app", _O,
                documentation_url=f"{docs}#inlinekeyboardbutton"),
            TelegramCapability("keyboard_button_login", "InlineKeyboardButton.login_url", _O,
                documentation_url=f"{docs}#inlinekeyboardbutton"),
            TelegramCapability("keyboard_button_switch_inline", "InlineKeyboardButton.switch_inline_query", _O,
                documentation_url=f"{docs}#inlinekeyboardbutton"),
            TelegramCapability("keyboard_button_copy_text", "InlineKeyboardButton.copy_text", _O,
                documentation_url=f"{docs}#inlinekeyboardbutton"),
            TelegramCapability("force_reply_in_keyboard", "InlineKeyboardMarkup.force_reply", _V,
                min_bot_api_version="10.3",
                documentation_url=f"{docs}#inlinekeyboardmarkup"),

            # ── Polls ─────────────────────────────────────────
            TelegramCapability("send_poll", "sendPoll", _O,
                notes="From Bot API 10.0: supports media in options and poll itself.",
                documentation_url=f"{docs}#sendpoll"),
            TelegramCapability("stop_poll", "stopPoll", _O,
                documentation_url=f"{docs}#stoppoll"),

            # ── Reactions (Bot API 7+) ────────────────────────
            TelegramCapability("set_message_reaction", "setMessageReaction", _O,
                permissions_required=["can_react"],
                documentation_url=f"{docs}#setmessagereaction"),
            TelegramCapability("delete_all_reactions", "deleteAllMessageReactions", _V,
                min_bot_api_version="10.0",
                availability=_A.ADMIN_REQUIRED,
                permissions_required=["can_delete_messages"],
                documentation_url=f"{docs}#deleteallmessagereactions"),

            # ── Inline mode ───────────────────────────────────
            TelegramCapability("inline_query", "answerInlineQuery", _O,
                notes="Requires inline mode enabled via @BotFather.",
                documentation_url=f"{docs}#answerinlinequery"),
            TelegramCapability("inline_query_cached", "InlineQueryResultCachedPhoto", _O,
                notes="Reuse Telegram file_ids for inline results.",
                documentation_url=f"{docs}#inlinequeryresultcachedphoto"),

            # ── Chat administration ───────────────────────────
            TelegramCapability("get_chat", "getChat", _O,
                documentation_url=f"{docs}#getchat"),
            TelegramCapability("get_chat_administrators", "getChatAdministrators", _O,
                documentation_url=f"{docs}#getchatadministrators"),
            TelegramCapability("kick_chat_member", "banChatMember", _O,
                availability=_A.ADMIN_REQUIRED,
                permissions_required=["can_restrict_members"],
                documentation_url=f"{docs}#banchatmember"),
            TelegramCapability("restrict_chat_member", "restrictChatMember", _O,
                availability=_A.ADMIN_REQUIRED,
                permissions_required=["can_restrict_members"],
                documentation_url=f"{docs}#restrictchatmember"),
            TelegramCapability("promote_chat_member", "promoteChatMember", _O,
                availability=_A.ADMIN_REQUIRED,
                permissions_required=["can_promote_members"],
                documentation_url=f"{docs}#promotechatmember"),
            TelegramCapability("set_chat_permissions", "setChatPermissions", _O,
                availability=_A.ADMIN_REQUIRED,
                permissions_required=["can_restrict_members"],
                documentation_url=f"{docs}#setchatpermissions"),
            TelegramCapability("create_chat_invite_link", "createChatInviteLink", _O,
                availability=_A.ADMIN_REQUIRED,
                permissions_required=["can_invite_users"],
                documentation_url=f"{docs}#createchatinvitelink"),

            # ── Join requests ─────────────────────────────────
            TelegramCapability("approve_join_request", "approveChatJoinRequest", _O,
                availability=_A.ADMIN_REQUIRED,
                permissions_required=["can_invite_users"],
                documentation_url=f"{docs}#approvechatjoinrequest"),
            TelegramCapability("decline_join_request", "declineChatJoinRequest", _O,
                availability=_A.ADMIN_REQUIRED,
                permissions_required=["can_invite_users"],
                documentation_url=f"{docs}#declinechatjoinrequest"),
            TelegramCapability("answer_join_request_query", "answerChatJoinRequestQuery", _V,
                min_bot_api_version="10.1",
                documentation_url=f"{docs}#answerchatjoinrequestquery"),

            # ── Forum topics ──────────────────────────────────
            TelegramCapability("create_forum_topic", "createForumTopic", _O,
                availability=_A.SUPERGROUPS_ONLY,
                permissions_required=["can_manage_topics"],
                documentation_url=f"{docs}#createforumtopic"),
            TelegramCapability("edit_forum_topic", "editForumTopic", _O,
                availability=_A.SUPERGROUPS_ONLY,
                permissions_required=["can_manage_topics"],
                documentation_url=f"{docs}#editforumtopic"),
            TelegramCapability("close_forum_topic", "closeForumTopic", _O,
                availability=_A.SUPERGROUPS_ONLY,
                permissions_required=["can_manage_topics"],
                documentation_url=f"{docs}#closeforumtopic"),

            # ── Communities (Bot API 10.2) ─────────────────────
            TelegramCapability("community_support", "Community", _V,
                min_bot_api_version="10.2",
                notes="Supergroups, channels and bots linked together around a shared topic.",
                documentation_url=f"{docs}#community"),

            # ── Guest Mode (Bot API 10.0) ─────────────────────
            TelegramCapability("guest_mode", "answerGuestQuery", _V,
                min_bot_api_version="10.0",
                notes="Bot responds in chats it is not a member of.",
                documentation_url=f"{docs}#answerguestquery"),

            # ── Payments & Stars ──────────────────────────────
            TelegramCapability("send_invoice", "sendInvoice", _O,
                documentation_url=f"{docs}#sendinvoice"),
            TelegramCapability("paid_media", "sendPaidMedia", _O,
                availability=_A.CHANNELS_ONLY,
                documentation_url=f"{docs}#sendpaidmedia"),
            TelegramCapability("telegram_stars", "getStarTransactions", _O,
                documentation_url=f"{docs}#getstartransactions"),

            # ── Business bots ─────────────────────────────────
            TelegramCapability("business_connection", "BusinessConnection", _O,
                notes="Bot manages business account messages.",
                documentation_url=f"{docs}#businessconnection"),
            TelegramCapability("secretary_bot", "SecretaryBot", _O,
                notes="Bot manages user account. Requires explicit user consent.",
                documentation_url=f"{docs}#secretary-bots"),
            TelegramCapability("managed_bots", "ManagedBotUpdated", _O,
                notes="Create and manage child bots.",
                documentation_url=f"{docs}#managedbotupdated"),

            # ── Webhooks / Updates ────────────────────────────
            TelegramCapability("set_webhook", "setWebhook", _O,
                notes="Webhook secret validation via X-Telegram-Bot-Api-Secret-Token header.",
                documentation_url=f"{docs}#setwebhook"),
            TelegramCapability("get_updates", "getUpdates", _O,
                notes="Long polling — mutually exclusive with webhook.",
                documentation_url=f"{docs}#getupdates"),

            # ── Bot commands ──────────────────────────────────
            TelegramCapability("set_my_commands", "setMyCommands", _O,
                documentation_url=f"{docs}#setmycommands"),
            TelegramCapability("ephemeral_commands", "BotCommand.is_ephemeral", _V,
                min_bot_api_version="10.2",
                notes="Commands that trigger ephemeral responses.",
                documentation_url=f"{docs}#botcommand"),

            # ── Mini Apps ─────────────────────────────────────
            TelegramCapability("web_app", "WebApp", _O,
                notes="Mini App URLs served over HTTPS. Origin policy hardened in Bot API 10.2.",
                documentation_url=f"{docs}#webappinfo"),
            TelegramCapability("web_app_data", "WebAppData", _O,
                documentation_url=f"{docs}#webappdata"),
            TelegramCapability("send_chat_join_request_webapp", "sendChatJoinRequestWebApp", _V,
                min_bot_api_version="10.1",
                documentation_url=f"{docs}#sendchatjoinrequestwebapp"),

            # ── Telegram Passport ─────────────────────────────
            TelegramCapability("passport", "PassportData", _O,
                notes="Encrypted identity document verification.",
                availability=_A.PRIVATE_ONLY,
                documentation_url=f"{docs}#passportdata"),

            # ── Confirmed unsupported / unavailable ───────────
            TelegramCapability(
                "read_messages",
                "getMessages",
                _U,
                notes="Bots cannot read arbitrary message history.",
                fallback="Store your own publish records in the database.",
            ),
            TelegramCapability(
                "get_user_count",
                "getChatMemberCount",
                _O,
                notes="Returns subscriber/member count. Views per post are NOT exposed.",
            ),
            TelegramCapability(
                "message_views",
                "N/A",
                _U,
                notes="Individual message view counts are NOT exposed by the Bot API.",
                fallback="Track user interactions (reactions, forwards) as a proxy.",
            ),
        ]

        for cap in caps:
            self.register(cap)


# Module-level singleton
_registry: TelegramCapabilityRegistry | None = None


def get_registry() -> TelegramCapabilityRegistry:
    global _registry
    if _registry is None:
        from app.core.config import settings
        _registry = TelegramCapabilityRegistry(settings.telegram_api_version)
    return _registry
