import datetime
from unittest.mock import MagicMock
from telethon.tl.types import (
    User as TelethonUser,
    Chat as TelethonChat,
    Channel as TelethonChannel,
    Message as TelethonMessage,
    MessageMediaContact,
    MessageMediaGeo,
    GeoPoint,
    PeerUser,
    PeerChannel,
)
from app.core.serializers import (
    serialize_user,
    serialize_chat,
    serialize_message,
    serialize_update,
)


def test_serialize_user():
    u = MagicMock(spec=TelethonUser)
    u.id = 123456789
    u.first_name = "Alice"
    u.last_name = "Smith"
    u.username = "alicesmith"
    u.phone = "+1234567890"
    u.bot = False
    u.lang_code = "en"

    serialized = serialize_user(u)
    assert serialized["id"] == 123456789
    assert serialized["is_bot"] is False
    assert serialized["first_name"] == "Alice"
    assert serialized["last_name"] == "Smith"
    assert serialized["username"] == "alicesmith"
    assert serialized["phone_number"] == "+1234567890"
    assert serialized["language_code"] == "en"


def test_serialize_chat_channel():
    ch = MagicMock(spec=TelethonChannel)
    ch.id = 987654321
    ch.title = "Tech Announcements"
    ch.username = "techchannel"
    ch.megagroup = False
    ch.gigagroup = False
    ch.about = "Official tech announcements channel"

    serialized = serialize_chat(ch)
    assert serialized["type"] == "channel"
    assert serialized["title"] == "Tech Announcements"
    assert serialized["username"] == "techchannel"
    assert serialized["bio"] == "Official tech announcements channel"


def test_serialize_chat_supergroup():
    sg = MagicMock(spec=TelethonChannel)
    sg.id = 11223344
    sg.title = "Python Developers"
    sg.username = "pydevs"
    sg.megagroup = True
    sg.gigagroup = False

    serialized = serialize_chat(sg)
    assert serialized["type"] == "supergroup"
    assert serialized["title"] == "Python Developers"


def test_serialize_message():
    m = MagicMock(spec=TelethonMessage)
    m.id = 42
    m.date = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
    m.chat_id = -100123456789
    m.raw_text = "Hello from UserAPI!"
    m.message = "Hello from UserAPI!"
    m.media = None
    m.reply_to = None
    m.forward = None
    m.edit_date = None

    # Sender mock
    sender = MagicMock(spec=TelethonUser)
    sender.id = 123
    sender.first_name = "Bob"
    sender.last_name = None
    sender.username = "bob"
    sender.bot = False
    m.sender = sender

    # Chat mock
    chat = MagicMock(spec=TelethonChannel)
    chat.id = 123456789
    chat.title = "Test Channel"
    chat.megagroup = False
    chat.gigagroup = False
    m.chat = chat

    serialized = serialize_message(m)
    assert serialized["message_id"] == 42
    assert serialized["text"] == "Hello from UserAPI!"
    assert serialized["from"]["id"] == 123
    assert serialized["from"]["first_name"] == "Bob"
    assert serialized["date"] == int(m.date.timestamp())


def test_serialize_update():
    m = MagicMock(spec=TelethonMessage)
    m.id = 100
    m.date = datetime.datetime.now(datetime.timezone.utc)
    m.chat_id = 123
    m.raw_text = "Incoming message"
    m.media = None
    m.sender = None
    m.chat = None
    m.reply_to = None
    m.forward = None
    m.edit_date = None

    upd = serialize_update(update_id=5001, message=m)
    assert upd["update_id"] == 5001
    assert upd["message"]["message_id"] == 100
    assert upd["message"]["text"] == "Incoming message"
