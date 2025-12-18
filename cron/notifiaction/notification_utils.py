import base64
import os
import json
import asyncio

import firebase_admin
from firebase_admin import credentials, messaging
from dotenv import load_dotenv
from googletrans import Translator

from cron.notifiaction.notification_message_utils import get_title_body_for_notification
from cron.utils import locales

topic_prefix_f1 = "ps_";
topic_prefix_moto_gp = "wheelie_";

topic_notification = "notification_";
topic_config_update = "config_update";

def __init_firebase_admin(is_prod: bool):
    service_account = __get_service_account_dict(is_prod)
    # Initialize Firebase Admin app only once
    if not firebase_admin._apps:
        cred = credentials.Certificate(service_account)
        firebase_admin.initialize_app(cred)
        print("Firebase Admin SDK initialized.")
    else:
        print("Firebase Admin SDK already initialized.")


def __get_service_account_dict(is_prod: bool=False):
    load_dotenv()
    if is_prod:
        config = os.getenv("FIREBASE_CONFIG_PROD")
    else:
        config = os.getenv("FIREBASE_CONFIG_DEV")
    json_bytes = base64.b64decode(config)
    service_account_dict = json.loads(json_bytes)
    print(f"Service account loaded for", "PROD" if is_prod else f"DEV:")
    # print(f"service_account_dict: {service_account_dict}")
    return service_account_dict

def __send_notification_to_topic_lang(is_f1: bool, title: str, body: str, lang_code: str):
    # Create a message to send to the topic
    if is_f1:
        notification_topic = topic_prefix_f1 + topic_notification + lang_code
    else:
        notification_topic = topic_prefix_moto_gp + topic_notification + lang_code

    data = {
        'type': notification_topic
    }
    message = messaging.Message(
        notification=messaging.Notification(
            title=title,
            body=body
        ),
        data=data if data else {},
        topic=notification_topic
    )

    # Send the message to the topic
    response = messaging.send(message)
    print(f"Successfully sent message to topic {notification_topic}: {response}")


async def send_notification_to_topic(is_f1: bool, is_prod: bool, title: str, body: str):
    __init_firebase_admin(is_prod=is_prod)
    translator = Translator()
    # Send notification for default (en) locale
    __send_notification_to_topic_lang(is_f1, title, body, "en")
    for locale in locales:
        try:
            translated_title_obj = await translator.translate(title, dest=locale)
            translated_desc_obj = await translator.translate(body, dest=locale)

            translated_title = translated_title_obj.text
            translated_desc = translated_desc_obj.text
            print(f"{locale} : title: {translated_title}")

            # Send notification for each locale
            __send_notification_to_topic_lang(is_f1, translated_title, translated_desc, locale)

        except Exception as e:
            print(f"⚠️ Translation failed for locale {locale}: {e}")
            print(f"   Skipping {locale} translation for this notification.")


async def send_config_update_notification(is_f1: bool, is_prod: bool, year: str, grand_prix_id: str):
    # send config update notification
    __init_firebase_admin(is_prod=is_prod)
    if is_f1:
        notification_topic = topic_prefix_f1 + topic_config_update
    else:
        notification_topic = topic_prefix_moto_gp + topic_config_update

    data = {
        'topic': notification_topic,
        'year': year,
        'grandPrixId': grand_prix_id,
    }
    message = messaging.Message(
        data=data if data else {},
        topic=notification_topic
    )

    # Send the message to the topic
    response = messaging.send(message)
    print(f"Successfully sent message to topic {notification_topic}: {response}")

def send_race_complete_notification(is_f1: bool, race_type: str, grand_prix):
    print(f"Sending race complete notification...for race type: {race_type}")
    title, body = get_title_body_for_notification(grand_prix, race_type)
    asyncio.run(send_notification_to_topic(is_f1=is_f1, is_prod=False, title=title, body=body))


if __name__ == "__main__":
    print("Testing notification utils...")
    # Send notification for default (en) locale
    # asyncio.run(send_notification_to_topic(is_prod=False, is_f1=True, title="Season summary for 2025", body="checkout season summary on the app!"))
    asyncio.run(send_config_update_notification(is_f1=True, is_prod=False, year="2024", grand_prix_id="some-event-id"))
