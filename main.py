import openai
import os
import json
from dotenv import load_dotenv
import re
import logging
import datetime
from textblob import TextBlob
import threading
from enum import Enum, auto

logging.basicConfig(
    filename='assistant.log',
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s:%(message)s'
)

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

ORDERS_FILE = "orders1.json"
CUSTOMERS_FILE = "customers1.json"
ORDER_ID_FILE = "last_order_id.txt"

ORDER_ID_LOCK = threading.Lock()

EXIT_PHRASES = [
    "exit", "quit", "bye", "goodbye", "see you", "later", "thanks",
    "thank you", "no, thanks", "i'm done", "that's all"
]

TIMEOUT_DURATION = 300

class ConversationState(Enum):
    GREETING = auto()
    ASK_PHONE = auto()
    CHECK_CUSTOMER = auto()
    ASK_NAME = auto()
    COLLECTING_ORDER = auto()
    ASK_EXTRAS_FOR_PIZZA = auto()
    ASK_BEVERAGES = auto()
    ASK_ADDITIONAL_EXTRAS = auto()
    ASK_DELIVERY_METHOD = auto()
    ASK_ADDRESS = auto()
    ASK_PAYMENT = auto()
    ASK_CARD_NUMBER = auto()
    ASK_CARD_EXPIRY = auto()
    ASK_CARD_CVV = auto()
    CONFIRM_ORDER = auto()
    END = auto()
    ASK_TOPPINGS = auto()

class ConversationTimer:
    def __init__(self, timeout, callback):
        self.timeout = timeout
        self.callback = callback
        self.timer = threading.Timer(self.timeout, self.callback)

    def reset(self):
        self.timer.cancel()
        self.timer = threading.Timer(self.timeout, self.callback)
        self.timer.start()

    def cancel(self):
        self.timer.cancel()

def on_timeout():
    logging.info("Conversation timed out due to inactivity.")

def load_data(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            try:
                data = json.load(file)
                return data
            except json.JSONDecodeError:
                logging.warning(f"{file_path} is empty or invalid. Initializing empty data.")
                return {}
    else:
        return {}

def save_data(file_path, data):
    with open(file_path, "w") as file:
        json.dump(data, file, indent=4)

def generate_order_id(orders):
    with ORDER_ID_LOCK:
        if not os.path.exists(ORDER_ID_FILE):
            with open(ORDER_ID_FILE, "w") as f:
                f.write("0000")

        with open(ORDER_ID_FILE, "r") as f:
            last_id_str = f.read().strip()
            try:
                last_id = int(last_id_str)
            except ValueError:
                logging.error(f"Invalid order ID in {ORDER_ID_FILE}. Resetting to 0000.")
                last_id = 0

        new_id = last_id + 1

        if new_id > 9999:
            logging.error("Order ID exceeded 9999. Resetting to 0001.")
            new_id = 1  
        new_id_str = f"{new_id:04d}"

        if new_id_str in orders:
            logging.error(f"Order ID {new_id_str} already exists. Incrementing to find a unique ID.")
            while new_id_str in orders and new_id <= 9999:
                new_id += 1
                if new_id > 9999:
                    new_id = 1
                new_id_str = f"{new_id:04d}"
            if new_id_str in orders:
                logging.critical("All order IDs from 0001 to 9999 are in use. Cannot generate a new order ID.")
                raise Exception("Order ID limit reached.")

        with open(ORDER_ID_FILE, "w") as f:
            f.write(new_id_str)

    return new_id_str

def is_negative_sentiment(user_input):
    analysis = TextBlob(user_input)
    return analysis.sentiment.polarity < -0.5

def should_end_conversation(user_input):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Determine if the user intends to end the conversation. Respond with 'yes' or 'no'."},
                {"role": "user", "content": user_input}
            ],
            max_tokens=3,
            temperature=0
        )
        decision = response.choices[0].message.content.strip().lower()
        return decision == "yes"
    except openai.error.OpenAIError as e:
        logging.error(f"Error in intent detection: {e}")
        return False

def suggest_upsells(order_details):
    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Suggest one complementary item based on the order. Keep it short and natural."},
                {"role": "user", "content": f"Order details: {order_details}"}
            ],
            max_tokens=50,
            temperature=0.5,
        )
        upsell = response.choices[0].message.content.strip()
        return upsell
    except openai.error.OpenAIError as e:
        logging.error(f"Error suggesting upsells: {e}")
        return ""

orders = load_data(ORDERS_FILE)
customers = load_data(CUSTOMERS_FILE)

session_data = {
    "state": ConversationState.GREETING,
    "phone_number": None,
    "customer_name": None,
    "order_details": {
        "pizzas": [],
        "beverages": [],
        "extras": [],
        "delivery_method": None,
        "address": None,
        "payment_method": None,
        "card_info": {
            "number": None,
            "expiry": None,
            "cvv": None
        },
        "order_time": None
    },
    "awaiting_pizza_details": False,
    "awaiting_extras_for_pizza": False,
    "awaiting_beverages": False,
    "awaiting_delivery_method": False,
    "awaiting_address": False,
    "awaiting_payment": False,
    "awaiting_confirmation": False
}

MENU = {
    "pizzas": {
        "Margherita": {
            "small": 10.99,
            "medium": 12.99,
            "large": 14.99,
            "description": "Classic tomato sauce, mozzarella, fresh basil"
        },
        "Pepperoni": {
            "small": 11.99,
            "medium": 13.99,
            "large": 15.99,
            "description": "Tomato sauce, mozzarella, pepperoni"
        },
        "Hawaiian": {
            "small": 12.99,
            "medium": 14.99,
            "large": 16.99,
            "description": "Tomato sauce, mozzarella, ham, pineapple"
        },
        "Supreme": {
            "small": 13.99,
            "medium": 15.99,
            "large": 17.99,
            "description": "Tomato sauce, mozzarella, pepperoni, sausage, mushrooms, peppers, onions"
        }
    },
    "sides": {
        "Garlic Bread": 4.99,
        "Chicken Wings (8pcs)": 8.99,
        "Cheese Sticks": 5.99,
        "Caesar Salad": 6.99
    },
    "drinks": {
        "Coca-Cola": 2.99,
        "Sprite": 2.99,
        "Fanta": 2.99,
        "Water": 1.99
    }
}

def display_menu():
    menu_text = "📋 SLICESYNC MENU 📋\n\n"
    
    menu_text += "🍕 PIZZAS:\n"
    for pizza, details in MENU["pizzas"].items():
        menu_text += f"\n{pizza}:\n"
        menu_text += f"  {details['description']}\n"
        menu_text += f"  Small: ${details['small']:.2f}\n"
        menu_text += f"  Medium: ${details['medium']:.2f}\n"
        menu_text += f"  Large: ${details['large']:.2f}\n"
    
    menu_text += "\n🍗 SIDES:\n"
    for side, price in MENU["sides"].items():
        menu_text += f"{side}: ${price:.2f}\n"
    
    menu_text += "\n🥤 DRINKS:\n"
    for drink, price in MENU["drinks"].items():
        menu_text += f"{drink}: ${price:.2f}\n"
    
    return menu_text

def start_conversation():
    global session_data
    session_data = reset_session_data()  # Reset session data to start fresh
    return "Welcome to SliceSync!\n\n" + display_menu() + "\n\nCan I get your phone number, please? (10 digits)"

def process_message(user_input):
    global session_data, orders, customers

    if session_data["state"] == ConversationState.GREETING:
        session_data["state"] = ConversationState.ASK_PHONE
        return "Welcome to SliceSync!\n\n" + display_menu() + "\n\nCan I get your phone number, please? (10 digits)"

    if any(phrase in user_input.lower() for phrase in EXIT_PHRASES):
        session_data["state"] = ConversationState.END
        return "Thanks for visiting SliceSync! Have a great day!"

    if is_negative_sentiment(user_input):
        return "I'm sorry to hear that. If you need further assistance, feel free to ask!"

    if should_end_conversation(user_input):
        session_data["state"] = ConversationState.END
        return "Thanks for visiting SliceSync! Have a great day!"

    state = session_data["state"]

    if state == ConversationState.ASK_PHONE:
        if re.match(r"^\d{10}$", user_input.strip()):
            session_data["phone_number"] = user_input.strip()
            if session_data["phone_number"] in customers:
                session_data["customer_name"] = customers[session_data["phone_number"]]["name"]
                session_data["state"] = ConversationState.COLLECTING_ORDER
                return f"Welcome back, {session_data['customer_name']}! What would you like to order?"
            else:
                session_data["state"] = ConversationState.ASK_NAME
                return "First time ordering with us? What's your name?"
        else:
            return "Please enter a valid 10-digit phone number."

    if state == ConversationState.ASK_NAME:
        session_data["customer_name"] = user_input.strip()
        customers[session_data["phone_number"]] = {"name": session_data["customer_name"], "order_history": []}
        save_data(CUSTOMERS_FILE, customers)
        session_data["state"] = ConversationState.COLLECTING_ORDER
        return f"Nice to meet you, {session_data['customer_name']}! What would you like to order?"

    if state == ConversationState.COLLECTING_ORDER:
        if user_input.lower() in ["menu", "show menu"]:
            return display_menu()
        
        pizza_pattern = r"(\d+)?\s*(small|medium|large)?\s*([a-zA-Z\s]*)?\s*pizza"
        match = re.search(pizza_pattern, user_input.lower())
        if match:
            quantity = int(match.group(1)) if match.group(1) else 1
            size = match.group(2).capitalize() if match.group(2) else "Medium"
            pizza_name = match.group(3).strip().title() if match.group(3) else None

            if not pizza_name:
                return "Please specify which pizza you'd like from our menu. Type 'menu' to see options."
            
            # Check if pizza exists in menu
            if pizza_name not in MENU["pizzas"]:
                return f"Sorry, we don't have {pizza_name} pizza. Type 'menu' to see our available options."

            session_data["order_details"]["pizzas"].append({
                "quantity": quantity,
                "size": size,
                "name": pizza_name,
                "price": MENU["pizzas"][pizza_name][size.lower()],
                "extras": []
            })
            
            session_data["state"] = ConversationState.ASK_EXTRAS_FOR_PIZZA
            return f"Would you like any extras for your {size} {pizza_name} pizza(s)? Type 'menu' to see available sides."
        else:
            return "Please specify your pizza order (e.g., '1 large Margherita pizza') or type 'menu' to see options."

    if state == ConversationState.ASK_TOPPINGS:
        if user_input.lower() not in ["no", "none", "n/a"]:
            toppings = [topping.strip().title() for topping in user_input.split(",")]
            session_data["order_details"]["pizzas"][-1]["toppings"] = ", ".join(toppings)
        else:
            session_data["order_details"]["pizzas"][-1]["toppings"] = "Cheese"
        session_data["state"] = ConversationState.ASK_EXTRAS_FOR_PIZZA
        return "Would you like any extras for your pizza(s)? (e.g., extra cheese, garlic sauce). If no, reply 'no'."

    if state == ConversationState.ASK_EXTRAS_FOR_PIZZA:
        if user_input.lower() not in ["no", "none", "n/a"]:
            extras = [extra.strip().title() for extra in user_input.split(",")]
            session_data["order_details"]["pizzas"][-1]["extras"] = extras
        session_data["state"] = ConversationState.ASK_BEVERAGES
        return "Would you like to add any beverages? (e.g., 2 coke, 1 sprite). If no, reply 'no'."

    if state == ConversationState.ASK_BEVERAGES:
        if user_input.lower() == "menu":
            return "\n".join([f"- {drink}" for drink in MENU["drinks"].keys()])
        
        if user_input.lower() not in ["no", "none", "n/a"]:
            beverage_pattern = r"(\d+)\s+([a-zA-Z\s]+)"
            matches = re.findall(beverage_pattern, user_input.lower())
            for q, item in matches:
                item = item.strip().title()
                if item not in MENU["drinks"]:
                    return f"Sorry, we don't have {item}. Please choose from our menu."
                session_data["order_details"]["beverages"].append({
                    "quantity": int(q),
                    "item": item,
                    "price": MENU["drinks"][item]
                })
        session_data["state"] = ConversationState.ASK_ADDITIONAL_EXTRAS
        return "Would you like to add any extras? (e.g., garlic bread, brownies). If no, reply 'no'."

    if state == ConversationState.ASK_ADDITIONAL_EXTRAS:
        if user_input.lower() not in ["no", "none", "n/a"]:
            extras_list = [extra.strip().title() for extra in user_input.split(",")]
            session_data["order_details"]["extras"] = extras_list
        session_data["state"] = ConversationState.ASK_DELIVERY_METHOD
        return "Would you like delivery or pickup?"

    if state == ConversationState.ASK_DELIVERY_METHOD:
        if user_input.lower() in ["delivery", "pickup"]:
            session_data["order_details"]["delivery_method"] = user_input.lower()
            if user_input.lower() == "delivery":
                session_data["state"] = ConversationState.ASK_ADDRESS
                return "Please provide your delivery address:"
            else:
                session_data["state"] = ConversationState.ASK_PAYMENT
                return "How would you like to pay? (cash/card)"
        else:
            return "Please specify either 'delivery' or 'pickup'."

    if state == ConversationState.ASK_ADDRESS:
        session_data["order_details"]["address"] = user_input.title()
        session_data["state"] = ConversationState.ASK_PAYMENT
        return "How would you like to pay? (cash/card)"

    if state == ConversationState.ASK_PAYMENT:
        if user_input.lower() in ["card", "credit card"]:
            session_data["order_details"]["payment_method"] = "Card"
            session_data["state"] = ConversationState.ASK_CARD_NUMBER
            return "Please enter your 16-digit card number:"
        else:
            session_data["order_details"]["payment_method"] = "Cash"
            order_summary = create_order_summary(session_data)
            session_data["state"] = ConversationState.CONFIRM_ORDER
            return order_summary + "\nWould you like to place this order? (yes/no)"

    if state == ConversationState.ASK_CARD_NUMBER:
        if validate_card_number(user_input):
            session_data["order_details"]["card_info"]["number"] = user_input
            session_data["state"] = ConversationState.ASK_CARD_EXPIRY
            return "Please enter the card expiry date (MM/YY format):"
        else:
            return "Invalid card number. Please enter a valid 16-digit card number:"

    if state == ConversationState.ASK_CARD_EXPIRY:
        if validate_expiry_date(user_input):
            session_data["order_details"]["card_info"]["expiry"] = user_input
            session_data["state"] = ConversationState.ASK_CARD_CVV
            return "Please enter the 3 or 4 digit CVV number:"
        else:
            return "Invalid expiry date. Please enter in MM/YY format:"

    if state == ConversationState.ASK_CARD_CVV:
        if validate_cvv(user_input):
            session_data["order_details"]["card_info"]["cvv"] = user_input
            order_summary = create_order_summary(session_data)
            session_data["state"] = ConversationState.CONFIRM_ORDER
            return order_summary + "\nWould you like to place this order? (yes/no)"
        else:
            return "Invalid CVV. Please enter a valid 3 or 4 digit CVV number:"

    if state == ConversationState.CONFIRM_ORDER:
        if user_input.lower() in ["yes", "y", "sure", "ok"]:
            session_data["order_details"]["order_time"] = str(datetime.datetime.now())
            order_id = generate_order_id(orders)
            orders[order_id] = {
                "customer_name": session_data["customer_name"],
                "phone_number": session_data["phone_number"],
                "order_details": session_data["order_details"],
                "status": "Received"
            }
            save_data(ORDERS_FILE, orders)
            customers[session_data["phone_number"]]["order_history"].append(order_id)
            save_data(CUSTOMERS_FILE, customers)
            msg = f"Great! Your order is confirmed. Your order number is {order_id}. "
            if session_data["order_details"]["delivery_method"] == "delivery":
                msg += "We'll deliver it to you soon!"
            else:
                msg += "It will be ready for pickup in about 20-25 minutes."
            session_data = reset_session_data()  
            return msg
        else:
            session_data["state"] = ConversationState.COLLECTING_ORDER
            return "No problem! Let me know if you'd like to make any changes or try something else."

    if state == ConversationState.END:
        session_data = reset_session_data()  
        return "Thanks for visiting SliceSync! Have a great day!"

    return "I'm not sure how to help with that. Please clarify."


def reset_session_data():
    return {
        "state": ConversationState.GREETING,
        "phone_number": None,
        "customer_name": None,
        "order_details": {
            "pizzas": [],
            "beverages": [],
            "extras": [],
            "delivery_method": None,
            "address": None,
            "payment_method": None,
            "card_info": {
                "number": None,
                "expiry": None,
                "cvv": None
            },
            "order_time": None
        },
        "awaiting_pizza_details": False,
        "awaiting_extras_for_pizza": False,
        "awaiting_beverages": False,
        "awaiting_delivery_method": False,
        "awaiting_address": False,
        "awaiting_payment": False,
        "awaiting_confirmation": False
    }

def validate_card_number(card_number):
    return bool(re.match(r'^\d{16}$', card_number))

def validate_expiry_date(expiry):
    # Format: MM/YY
    if not re.match(r'^\d{2}/\d{2}$', expiry):
        return False
    
    try:
        month, year = map(int, expiry.split('/'))
        if not (1 <= month <= 12):
            return False
        
        current_year = datetime.datetime.now().year % 100
        current_month = datetime.datetime.now().month
        
        if year < current_year or (year == current_year and month < current_month):
            return False
        
        return True
    except:
        return False

def validate_cvv(cvv):
    return bool(re.match(r'^\d{3,4}$', cvv))

def create_order_summary(session_data):
    order_summary = "Let me confirm your order:\n"
    for pizza in session_data["order_details"]["pizzas"]:
        order_summary += f"- {pizza['quantity']} {pizza['size']} pizza(s)"
        if pizza.get('toppings'):
            order_summary += f" with {pizza['toppings']}\n"
        if pizza.get('extras'):
            order_summary += f"  Extras: {', '.join(pizza['extras'])}\n"
    for beverage in session_data["order_details"]["beverages"]:
        order_summary += f"- {beverage['quantity']} {beverage['item']}\n"
    if session_data["order_details"]["extras"]:
        order_summary += f"- Extras: {', '.join(session_data['order_details']['extras'])}\n"
    order_summary += f"- {session_data['order_details']['delivery_method'].title()}"
    if session_data['order_details']['address']:
        order_summary += f"\n- Delivery to: {session_data['order_details']['address']}"
    order_summary += f"\n- Payment: {session_data['order_details']['payment_method']}"
    if session_data['order_details']['payment_method'] == "Card":
        card_info = session_data['order_details']['card_info']
        if card_info['number']:
            masked_card = '*' * 12 + card_info['number'][-4:]
            order_summary += f" (Card ending in {card_info['number'][-4:]}"
            if card_info['expiry']:
                order_summary += f", expires {card_info['expiry']}"
            order_summary += ")"
    order_summary += "\n"
    return order_summary
