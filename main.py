import logging
import uuid
import psycopg2
import json
import os

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext

log_filename = 'log.txt'
logging.basicConfig(filename=log_filename, level=logging.INFO,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

logger.info('Service start')

CONFIG_FILE = 'config.json'


def create_empty_config():
    empty_config = {}
    with open(CONFIG_FILE, 'w') as config_file:
        json.dump(empty_config, config_file)
        logger.info(f'Create empty {CONFIG_FILE}')


def load_config():
    if not os.path.exists(CONFIG_FILE):
        create_empty_config()

    with open(CONFIG_FILE) as config_file:
        logger.info(f'Load {CONFIG_FILE}')
        return json.load(config_file)


def save_config(config):
    with open(CONFIG_FILE, 'w') as config_file:
        json.dump(config, config_file, indent=4)
        logger.info(f'Save updates {CONFIG_FILE}')


config = load_config()

if 'nowpayments_api_key' not in config:
    config['nowpayments_api_key'] = ""
if 'telegram_token' not in config:
    config['telegram_token'] = ""
if 'base_url' not in config:
    config['base_url'] = ""
if 'login_payments' not in config:
    config['login_payments'] = ""
if 'pass_payments' not in config:
    config['pass_payments'] = ""
if 'price' not in config:
    config['price'] = 5
if 'help_user_id' not in config:
    config['help_user_id'] = ""
if 'db_name' not in config:
    config['db_name'] = ""
if 'user_db' not in config:
    config['user_db'] = ""
if 'pass_db' not in config:
    config['pass_db'] = ""
if 'host_db' not in config:
    config['host_db'] = ""
if 'port_db' not in config:
    config['port_db'] = ""

save_config(config)

NOWPAYMENTS_API_KEY = config.get("nowpayments_api_key")
TOKEN = config.get("telegram_token")
BASE_URL = config.get("base_url")
LOGIN_PAYMENTS = config.get("login_payments")
PASS_PAYMENTS = config.get("pass_payments")
PRICE = config.get("price")
HELP_USER_ID = config.get("help_user_id")
ADMINS = config.get("admins")

DB_NAME = config.get("db_name")
USER_DB = config.get("user_db")
PASS_DB = config.get("pass_db")
HOST_DB = config.get("host_db")
PORT_DB = config.get("port_db")

conn = psycopg2.connect(
    dbname=f"{DB_NAME}",
    user=f"{USER_DB}",
    password=f"{PASS_DB}",
    host=f"{HOST_DB}",
    port=f"{PORT_DB}"
)

cursor = conn.cursor()

with conn:
    with conn.cursor() as cursor:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id bigint PRIMARY KEY,
                username TEXT,
                register_timestamp TIMESTAMP DEFAULT current_timestamp,
                last_interaction TIMESTAMP
            )
        ''')
        logger.info('Table users create')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id SERIAL PRIMARY KEY,
                uuid TEXT,
                username TEXT,
                is_paid BOOLEAN DEFAULT FALSE,
                invoice_id TEXT,
                is_use_for_ticket BOOLEAN DEFAULT FALSE,
                payment_timestamp TIMESTAMP
            )
        ''')

        logger.info('Table transactions create')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                text TEXT,
                path_to_photo TEXT,
                path_to_video TEXT
            )
        ''')
        logger.info('Table messages create')

        cursor.execute('''CREATE TABLE IF NOT EXISTS invoices
                      (id SERIAL PRIMARY KEY, 
                       order_id TEXT NOT NULL, 
                       username TEXT NOT NULL, 
                       record_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()

        logger.info('Table invoices create')


def start(update):
    user = update.message.from_user
    username = user.username
    user_id = user.id

    with conn:
        with conn.cursor() as cursor:
            cursor.execute('SELECT * FROM users WHERE user_id = %s', (user_id,))
            user_entry = cursor.fetchone()

            if not user_entry:
                cursor.execute(
                    'INSERT INTO users (user_id, username, register_timestamp) VALUES (%s, %s, current_timestamp)',
                    (user_id, username)
                )
                conn.commit()
            else:
                cursor.execute(
                    'UPDATE users SET last_interaction = current_timestamp WHERE user_id = %s',
                    (user_id,)
                )
                conn.commit()

    keyboard = [
        [InlineKeyboardButton("Buy_goods", callback_data='buy_ticket')],
        [InlineKeyboardButton("Terms", callback_data='terms')]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    update.message.reply_text(f'Hello, {username}!',
                              reply_markup=reply_markup)


def button_click(update, context: CallbackContext):
    query = update.callback_query
    user = query.from_user
    username = user.username
    query.answer()
    button_id = query.data

    if button_id == 'buy_ticket':
        logger.info(f'Username = {username} pressed the button {button_id}')
        order_id = str(uuid.uuid4())
        logger.info(f'Generate order_id = {order_id}')
        keyboard = [
            [InlineKeyboardButton("🛒 Buy", callback_data=f'confirm_{order_id}')],
            [InlineKeyboardButton("🔙 Back", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text=f"The price is: {PRICE} usd.",
                                reply_markup=reply_markup)
    elif button_id.startswith('confirm_'):
        logger.info(f'Username = {username} pressed the button {button_id}')
        order_id = button_id.split("_")[1]
        payment = create_invoice(update, context, order_id)
        logger.info(f'Create invoice = {payment}')
        payment_link = payment["invoice_url"]
        keyboard = [
            [InlineKeyboardButton("Pay", url=f"{payment_link}")],
            [InlineKeyboardButton("I Paid", callback_data=f'paid_{order_id}')],
            [InlineKeyboardButton("Back", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text=f"Order {order_id} create."
                                     f"Press button \"Pay\" to pay for order."
                                     f"After payment click the button \"I paid\"",
                                reply_markup=reply_markup)
    elif button_id.startswith("paid_"):
        logger.info(f'Username = {username} pressed the button {button_id}')
        order_id = button_id.split("_")[1]
        keyboard = [
            [InlineKeyboardButton("Check transaction", callback_data=f'check_{order_id}')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text=f"Press \"Check transaction\", to verify a transaction {order_id}"
                                , reply_markup=reply_markup)

    elif button_id.startswith("check_"):
        logger.info(f'Username = {username} pressed the button {button_id}')
        order_id = button_id.split("_")[1]
        if api_check():
            transaction_in = is_transaction_in(update, context, order_id)
            if is_transaction_in:
                status = check_pay(update, context, transaction_in)
                if status:
                    if status == "finished":  # finished
                        with conn:
                            with conn.cursor() as cursor:
                                cursor.execute(
                                    'UPDATE transactions SET is_paid = TRUE, is_use_for_ticket = TRUE WHERE uuid = %s',
                                    (order_id,)
                                )
                                logger.info(f'For order_id =  {order_id} change is_paid and is_use_for_ticket to TRUE')
                                cursor.execute(
                                    'INSERT INTO tickets (username, uuid, ticket_timestamp) VALUES (%s, %s, current_timestamp)',
                                    (username, order_id)
                                )
                        keyboard = [
                            [InlineKeyboardButton("Back to main menu", callback_data='back')]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        query.edit_message_text(
                            text=f"Transaction successful!",
                            reply_markup=reply_markup)

                    elif status == "waiting":  # waiting
                        keyboard = [
                            [InlineKeyboardButton("Check transaction", callback_data=f'check_{order_id}')]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        query.edit_message_text(
                            text=f"Status is waiting. Press \"Check transaction\" to check transaction again {order_id}"
                            , reply_markup=reply_markup)

                    elif status == "confirming":
                        keyboard = [
                            [InlineKeyboardButton("Check transaction", callback_data=f'check_{order_id}')]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        query.edit_message_text(
                            text=f"The transaction is processed on the blockchain. "
                                 f"Press \"Check transaction\" to check transaction again {order_id}"
                            , reply_markup=reply_markup)

                    elif status == "confirmed":
                        keyboard = [
                            [InlineKeyboardButton("Check transaction", callback_data=f'check_{order_id}')]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        query.edit_message_text(
                            text=f"The transaction is confirmed by the blockchain"
                                 f".Press \"Check transaction\" to check transaction again {order_id}"
                            , reply_markup=reply_markup)

                    elif status == "sending":
                        keyboard = [
                            [InlineKeyboardButton("Check transaction", callback_data=f'check_{order_id}')]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        query.edit_message_text(
                            text=f"Funds sent, please wait."
                                 f" Press \"Check transaction\" to check transaction again {order_id}"
                            , reply_markup=reply_markup)

                    elif status == "partially_paid":
                        add_invoice(order_id, username)
                        keyboard = [
                            [InlineKeyboardButton("Send an invoice to the operator", callback_data=f'help_{order_id}')],
                            [InlineKeyboardButton("Back", callback_data='back')]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        query.edit_message_text(
                            text=f"The amount sent is less than required. Send an invoice to the operator"
                            , reply_markup=reply_markup)

                    elif status == "failed":
                        add_invoice(order_id, username)
                        keyboard = [
                            [InlineKeyboardButton("Send an invoice to the operator", callback_data=f'help_{order_id}')],
                            [InlineKeyboardButton("Back", callback_data='back')]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        query.edit_message_text(
                            text=f"Payment failed due to an error. Send an invoice to the operator"
                            , reply_markup=reply_markup)

                    elif status == "refunded":
                        add_invoice(order_id, username)
                        keyboard = [
                            [InlineKeyboardButton("Send an invoice to the operator", callback_data=f'help_{order_id}')],
                            [InlineKeyboardButton("Back", callback_data='back')]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        query.edit_message_text(
                            text=f"The funds have been returned to the user. Send an invoice to the operator"
                            , reply_markup=reply_markup)

                    elif status == "expired":
                        keyboard = [
                            [InlineKeyboardButton("Back", callback_data='back')]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        query.edit_message_text(
                            text=f"Payment is overdue. Funds not sent within 7 days."
                            , reply_markup=reply_markup)
                    else:
                        add_invoice(order_id, username)
                        keyboard = [
                            [InlineKeyboardButton("Send an invoice to the operator", callback_data=f'help_{order_id}')],
                            [InlineKeyboardButton("Back", callback_data='back')]
                        ]
                        reply_markup = InlineKeyboardMarkup(keyboard)
                        query.edit_message_text(
                            text=f"Transaction {order_id} not found. Send an invoice to the operator"
                            , reply_markup=reply_markup)
                else:
                    logger.info(f' For order_id = {order_id} and username = {username} '
                                f'not found transaction if status:')
                    add_invoice(order_id, username)
                    keyboard = [
                        [InlineKeyboardButton("Send an invoice to the operator", callback_data=f'help_{order_id}')],
                        [InlineKeyboardButton("Back", callback_data='back')]
                    ]
                    reply_markup = InlineKeyboardMarkup(keyboard)
                    query.edit_message_text(
                        text=f"Transaction {order_id} not found. Send an invoice to the operator"
                        , reply_markup=reply_markup)
            else:
                logger.info(f'For order_id = {order_id} and username = {username} '
                            f'not found transaction if is_transaction_in:')
                add_invoice(order_id, username)
                keyboard = [
                    [InlineKeyboardButton("Send an invoice to the operator", callback_data=f'help_{order_id}')],
                    [InlineKeyboardButton("Back", callback_data='back')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                query.edit_message_text(text=f"Transaction {order_id} not found. Send an invoice to the operator"
                                        , reply_markup=reply_markup)
        else:
            logger.info(f'For order_id = {order_id} and username = {username} '
                        f'api service unavailable, if api_check(): gave False')
            keyboard = [
                [InlineKeyboardButton("Check transaction", callback_data=f'check_{order_id}')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            query.edit_message_text(text=f"Temporary unavailability of transaction verification. Please wait."
                                         f"Press \"Check transaction\" to check transaction again {order_id}"
                                    , reply_markup=reply_markup)

    elif button_id == 'back':
        logger.info(f'Username = {username} pressed the button {button_id}')
        keyboard = [
            [InlineKeyboardButton("Buy", callback_data='buy_ticket')],
            [InlineKeyboardButton("Terms", callback_data='terms')]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        query.edit_message_text(f'Hello, {username}!',
                                reply_markup=reply_markup)

    elif button_id.startswith('help_'):
        logger.info(f'Username = {username} pressed the button {button_id}')
        order_id = button_id.split("_")[1]
        send_private_message(update, context, order_id)
        logger.info(f'From username = {username} send message to the operator about order_id = {order_id}')
        keyboard = [
            [InlineKeyboardButton("Main menu", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(text=f"Message sent to the operator! Wait for feedback."
                                , reply_markup=reply_markup)


    elif button_id == 'terms':
        logger.info(f'Username = {username} pressed the button {button_id}')
        keyboard = [
            [InlineKeyboardButton("Main menu", callback_data='back')]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)

        query.edit_message_text(f'Hello, {username}!',
                                reply_markup=reply_markup)


def create_invoice(update: Update, order_id):
    query = update.callback_query
    user = query.from_user
    username = user.username
    headers = {
        "x-api-key": f"{NOWPAYMENTS_API_KEY}"
    }

    payload = {
        "price_amount": f"{PRICE}",
        "price_currency": "usd",
        "order_id": order_id,
        "order_description": "Ticket"
    }

    response = requests.post(f"{BASE_URL}/v1/invoice", json=payload, headers=headers)
    logger.info(f'username = {username} create invoice =  {response}')
    data = response.json()
    logger.info(f'username = {username} data = {data}')
    with conn:
        with conn.cursor() as cursor:
            cursor.execute(
                'INSERT INTO transactions (uuid, username, invoice_id, payment_timestamp) VALUES (%s, %s, %s, '
                'current_timestamp)',
                (order_id, username, data["id"])
            )
            logger.info(f'For username = {username} issued order_id = {order_id} and invoice_id = {data["id"]}')

    return data


def is_transaction_in(order_id):
    with conn.cursor() as cursor:
        cursor.execute(
            'SELECT invoice_id FROM transactions WHERE uuid = %s AND is_use_for_ticket = FALSE ORDER BY payment_timestamp DESC LIMIT 1',
            (order_id,)
        )
        transaction_entry = cursor.fetchone()
        logger.info(
            f'In func is_transaction_in for order_id = {order_id}, invoice_id = {transaction_entry} where '
            f'is_use_for_ticket = FALSE')

    return transaction_entry


def check_pay(transaction_entry):
    invoice_id = transaction_entry[0]
    logger.info(
        f'In func check_pay for transaction_entry = {transaction_entry}, invoice_id = {invoice_id}')
    status = None
    try:
        status = check_payment_by_payment_id(list_of_payments(invoice_id))
        logger.info(
            f'In func check_pay status = {status} for invoice_id = {invoice_id}')
    except Exception as e:
        logger.error(f'In func check_pay for invoice_id = {invoice_id} error: {e}')
    return status


def api_check():
    response = requests.get(f"{BASE_URL}/v1/status")
    logger.info(f'In func api_check response = {response}')

    data = response.json()
    return data["message"] == 'OK'


def auth():
    body = {
        "email": f"{LOGIN_PAYMENTS}",
        "password": f"{PASS_PAYMENTS}"
    }
    response = requests.post(f"{BASE_URL}/v1/auth", json=body)
    data = response.json()
    token = None
    try:
        token = data["token"]
        logger.info(f'In func auth token successfully return')
    except Exception as e:
        logger.error(f'In func auth error: {e}')
    return token


def list_of_payments(invoice_id):
    token = auth()

    headers = {
        "x-api-key": f"{NOWPAYMENTS_API_KEY}",
        "Authorization": f"Bearer {token}"
    }
    response = requests.get(f"{BASE_URL}/v1/payment/?invoiceId={invoice_id}"
                            , headers=headers)
    json_response = response.json()
    payment_id = None
    try:
        payment_id = json_response['data'][0]['payment_id']
        logger.info(f'In func list_of_payments for invoice_id = {invoice_id} payment_id = {payment_id}')
    except Exception as e:
        logger.error(f'In func list_of_payments for invoice_id = {invoice_id} error: {e}')
    return payment_id


def check_payment_by_payment_id(payment_id):
    headers = {
        "x-api-key": f"{NOWPAYMENTS_API_KEY}"
    }
    response = requests.get(f"{BASE_URL}/v1/payment/{payment_id}"
                            , headers=headers)
    data = response.json()
    payment_status = None
    try:
        payment_status = data["payment_status"]
        logger.info(
            f'in func check_payment_by_payment_id for payment_id = {payment_id} payment_status = {payment_status}')
    except Exception as e:
        logger.error(f'In func check_payment_by_payment_id for payment_id = {payment_id} error: {e}')
    return payment_status


def send_private_message(update: Update, context: CallbackContext, order_id) -> None:
    try:
        context.bot.send_message(chat_id=f'{HELP_USER_ID}', text=f"Someone have issues with {order_id}")
        logger.info(
            f'In func send_private_message for order_id = {order_id} send message for operator')
    except Exception as e:
        logger.error(f'In func send_private_message for order_id = {order_id} error: {e}')


def get_last_message():
    with conn.cursor() as cursor:
        cursor.execute("SELECT * FROM messages ORDER BY id DESC LIMIT 1")
        message = cursor.fetchone()
        if not message:
            return {}
        columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, message))


def get_all_users():
    with conn.cursor() as cursor:
        cursor.execute("SELECT user_id FROM users")
        users = cursor.fetchall()
    return [user[0] for user in users]


def send_message_to_all(update, context):
    user_id = update.message.from_user.id
    if user_id not in ADMINS:
        logger.info(
            f'In func send_message_to_all user_id = {user_id}. {user_id} don\'t have permissions for this command!')
        update.message.reply_text("You don't have permissions for this command")
        return
    message = get_last_message()
    all_users = get_all_users()

    for user in all_users:

        if message.get("text"):
            context.bot.send_message(chat_id=user, text=message.get("text"))

        if message.get("path_to_photo"):
            with open(message["path_to_photo"], "rb") as photo:
                context.bot.send_photo(chat_id=user, photo=photo)

        if message.get("path_to_video"):
            with open(message["path_to_video"], "rb") as video:
                context.bot.send_video(chat_id=user, video=video)


def add_invoice(order_id, username):
    with conn.cursor() as cursor:
        cursor.execute('INSERT INTO invoices (order_id, username) VALUES (%s, %s)',
                       (order_id, username))
        conn.commit()


def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CallbackQueryHandler(button_click))

    dp.add_handler(CallbackQueryHandler(button_click, pattern='button_click'))

    dp.add_handler(CommandHandler("send_message_to_all", send_message_to_all))

    updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
