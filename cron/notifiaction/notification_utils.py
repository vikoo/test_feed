import base64
import os
import json
import asyncio

import firebase_admin
from firebase_admin import credentials, messaging
from dotenv import load_dotenv
from googletrans import Translator
from loguru import logger

from cron.notifiaction.notification_message_utils import get_title_body_for_notification
from cron.utils import locales

topic_prefix_f1 = "ps_"
topic_prefix_moto_gp = "wheelie_"

topic_notification = "notification_"
topic_config_update = "config_update"

def __init_firebase_admin(is_prod: bool):
    service_account = __get_service_account_dict(is_prod)
    # Initialize Firebase Admin app only once
    if not firebase_admin._apps:
        cred = credentials.Certificate(service_account)
        firebase_admin.initialize_app(cred)
        logger.info("Firebase Admin SDK initialized.")
    else:
        logger.info("Firebase Admin SDK already initialized.")


def __get_service_account_dict(is_prod: bool=False):
    load_dotenv()
    if is_prod:
        config = os.getenv("FIREBASE_CONFIG_PROD")
    else:
        config = os.getenv("FIREBASE_CONFIG_DEV")
    json_bytes = base64.b64decode(config)
    service_account_dict = json.loads(json_bytes)
    logger.info(f"Service account loaded for {'PROD' if is_prod else 'DEV'}")
    # logger.debug(f"service_account_dict: {service_account_dict}")
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
    logger.info(f"Successfully sent message to topic {notification_topic}: {response}")


async def send_notification_to_topic(is_f1: bool, is_prod: bool, title: str, body: str):
    __init_firebase_admin(is_prod=is_prod)
    translator = Translator()
    # Send notification for default (en) locale
    __send_notification_to_topic_lang(is_f1, title, body, "en")
    for locale in locales:
        try:
            if locale == "zh":
                translate_locale = "zh-CN"
            else:
                translate_locale = locale
            translated_title_obj = translator.translate(title, dest=translate_locale)
            translated_desc_obj = translator.translate(body, dest=translate_locale)

            translated_title = translated_title_obj.text
            translated_desc = translated_desc_obj.text
            logger.debug(f"{locale} : title: {translated_title}")

            # Send notification for each locale
            __send_notification_to_topic_lang(is_f1, translated_title, translated_desc, locale)

        except Exception as e:
            logger.warning(f"Translation failed for locale {locale}: {e}")
            logger.warning(f"Skipping {locale} translation for this notification.")


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
    logger.info(f"Successfully sent message to topic {notification_topic}: {response}")

def send_race_complete_notification(is_f1: bool, race_type: str, grand_prix):
    logger.info(f"Sending race complete notification...for race type: {race_type}")
    try:
        title, body = get_title_body_for_notification(grand_prix, race_type)
        asyncio.run(send_notification_to_topic(is_f1=is_f1, is_prod=True, title=title, body=body))
        logger.info("Notification sent successfully")
    except ValueError as e:
        logger.warning(f"Skipping notification - Firebase configuration error: {e}")
        logger.warning("Continuing without sending notification...")
    except Exception as e:
        logger.warning(f"Failed to send notification: {type(e).__name__}: {e}")
        logger.warning("Continuing without sending notification...")


if __name__ == "__main__":
    logger.info("Testing notification utils...")
    # Send notification for default (en) locale
    # asyncio.run(send_notification_to_topic(is_prod=False, is_f1=True, title="Season summary for 2025", body="checkout season summary on the app!"))
    asyncio.run(send_config_update_notification(is_f1=True, is_prod=True, year="2024", grand_prix_id="some-event-id"))
