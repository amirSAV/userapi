from typing import Optional, Union, List, Dict, Any
from pydantic import BaseModel, Field


class TelegramResponse(BaseModel):
    """Standard Telegram Bot API response structure."""
    ok: bool
    result: Optional[Any] = None
    error_code: Optional[int] = None
    description: Optional[str] = None


class RegisterStringRequest(BaseModel):
    api_id: int = Field(..., description="Telegram API ID from my.telegram.org")
    api_hash: str = Field(..., description="Telegram API Hash from my.telegram.org")
    session_string: str = Field(..., description="Telethon StringSession")
    proxy: Optional[Union[str, Dict[str, Any]]] = Field(None, description="Optional proxy URL or dict")


class SendCodeRequest(BaseModel):
    phone_number: str = Field(..., description="Phone number in international format (+1234567890)")
    api_id: int = Field(..., description="Telegram API ID")
    api_hash: str = Field(..., description="Telegram API Hash")
    proxy: Optional[Union[str, Dict[str, Any]]] = Field(None, description="Optional proxy")


class SignInRequest(BaseModel):
    auth_token: str = Field(..., description="Temporary auth token from send_code")
    code: str = Field(..., description="SMS / Telegram confirmation code")


class PasswordRequest(BaseModel):
    auth_token: str = Field(..., description="Temporary auth token")
    password: str = Field(..., description="Two-step verification 2FA password")


class RegisterBotRequest(BaseModel):
    bot_token: str = Field(..., description="Official Telegram Bot token (from @BotFather)")
    proxy: Optional[Union[str, Dict[str, Any]]] = Field(None, description="Optional proxy URL or dict")


class RotateTokenRequest(BaseModel):
    token: Optional[str] = Field(None, description="Current API token (if not specified in URL path)")
    new_token: Optional[str] = Field(None, description="Optional custom new token; auto-generated if omitted")


class UnlinkSessionRequest(BaseModel):
    token: Optional[str] = Field(None, description="Token to unlink")
    delete_file: bool = Field(True, description="Whether to delete the .session file from disk")


class TerminateSessionRequest(BaseModel):
    token: Optional[str] = Field(None, description="Token to terminate on Telegram")



class ProxyModel(BaseModel):
    type: str = Field(..., description="Proxy type: socks5, socks4, http, mtproto")
    host: str = Field(..., description="Proxy server address or IP")
    port: int = Field(..., description="Proxy server port")
    username: Optional[str] = Field(None, description="Username for SOCKS5/HTTP")
    password: Optional[str] = Field(None, description="Password for SOCKS5/HTTP")
    secret: Optional[str] = Field(None, description="Secret key for MTProto proxy")
    rdns: bool = Field(True, description="Remote DNS resolution for SOCKS5")


class SetProxyRequest(BaseModel):
    proxy: Union[str, ProxyModel, Dict[str, Any]] = Field(..., description="Proxy URL or specification object")


class SetWebhookRequest(BaseModel):
    url: str = Field(..., description="HTTPS/HTTP URL to receive incoming updates")


class SendMessageRequest(BaseModel):
    chat_id: Union[int, str]
    text: str
    parse_mode: Optional[str] = None
    reply_to_message_id: Optional[int] = None
    disable_web_page_preview: Optional[bool] = None
    disable_notification: Optional[bool] = None
    schedule_date: Optional[int] = None
    reply_markup: Optional[Dict[str, Any]] = None


class ForwardMessageRequest(BaseModel):
    chat_id: Union[int, str]
    from_chat_id: Union[int, str]
    message_id: int
    disable_notification: Optional[bool] = None


class CopyMessageRequest(BaseModel):
    chat_id: Union[int, str]
    from_chat_id: Union[int, str]
    message_id: int
    caption: Optional[str] = None
    parse_mode: Optional[str] = None


class EditMessageTextRequest(BaseModel):
    chat_id: Union[int, str]
    message_id: int
    text: str
    parse_mode: Optional[str] = None
    disable_web_page_preview: Optional[bool] = None


class EditMessageCaptionRequest(BaseModel):
    chat_id: Union[int, str]
    message_id: int
    caption: Optional[str] = None
    parse_mode: Optional[str] = None


class DeleteMessageRequest(BaseModel):
    chat_id: Union[int, str]
    message_id: int


class DeleteMessagesRequest(BaseModel):
    chat_id: Union[int, str]
    message_ids: List[int]


class PinChatMessageRequest(BaseModel):
    chat_id: Union[int, str]
    message_id: int
    disable_notification: Optional[bool] = None


class UnpinChatMessageRequest(BaseModel):
    chat_id: Union[int, str]
    message_id: Optional[int] = None


class SendChatActionRequest(BaseModel):
    chat_id: Union[int, str]
    action: str


class JoinChatRequest(BaseModel):
    chat_id: Optional[Union[int, str]] = None
    invite_link: Optional[str] = None


class MarkAsReadRequest(BaseModel):
    chat_id: Union[int, str]
    max_id: Optional[int] = None


class AddContactRequest(BaseModel):
    phone_number: str
    first_name: str
    last_name: Optional[str] = ""
