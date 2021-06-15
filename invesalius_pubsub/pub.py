"""A wrapper around pypubsub package that allows adding hooks.

"""

from typing import Callable

from pubsub import pub as Publisher
from pubsub.core.listener import UserListener

__all__ = [
    # subscribing
    'subscribe',
    'unsubscribe',

    # publishing
    'sendMessage',

    # adding hooks
    'add_sendMessage_hook'
]

sendMessage_hook = None
subscribe_hook = None

def add_sendMessage_hook(hook: Callable[[str, dict], None]):
    global sendMessage_hook
    sendMessage_hook = hook

def add_subscribe_hook(hook: Callable[[str, dict], None]):
    global subscribe_hook
    subscribe_hook = hook

def subscribe(listener: UserListener, topicName: str, **curriedArgs):
    subscribedListener, success = Publisher.subscribe(listener, topicName, **curriedArgs)
    if subscribe_hook is not None:
        subscribe_hook(listener, topicName)
    return subscribedListener, success

def unsubscribe(*args, **kwargs):
    Publisher.unsubscribe(*args, **kwargs)

def sendMessage(topicName: str, **msgdata):
    Publisher.sendMessage(topicName, **msgdata)
    if sendMessage_hook is not None:
        sendMessage_hook(topicName, msgdata)

def sendMessage_no_hook(topicName: str, **msgdata):
    Publisher.sendMessage(topicName, **msgdata)

AUTO_TOPIC = Publisher.AUTO_TOPIC
