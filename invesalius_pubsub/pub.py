"""A wrapper around pypubsub package that allows adding hooks.

"""

from typing import Callable

from pubsub import pub as Publisher

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

def add_sendMessage_hook(hook: Callable[[str, dict], None]):
    global sendMessage_hook
    sendMessage_hook = hook

def subscribe(*args, **kwargs):
    Publisher.subscribe(*args, **kwargs)

def unsubscribe(*args, **kwargs):
    Publisher.unsubscribe(*args, **kwargs)

def sendMessage(topicName: str, **msgdata):
    Publisher.sendMessage(topicName, **msgdata)
    if sendMessage_hook is not None:
        sendMessage_hook(topicName, msgdata)

AUTO_TOPIC = Publisher.AUTO_TOPIC
