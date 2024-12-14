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

# Configure logging
logging.basicConfig(
    filename='assistant.log',
    level=logging.INFO,
    format='%(asctime)s:%(levelname)s:%(message)s'
)

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# File paths
ORDERS_FILE = "orders1.json"
CUSTOMERS_FILE = "customers1.json"
ORDER_ID_FILE = "last_order_id.txt"

# Initialize a lock for thread safety
ORDER_ID_LOCK = threading.Lock()

EXIT_PHRASES = [
    "exit", "quit", "bye", "goodbye", "see you", "later", "thanks",
    "thank you", "no, thanks", "i'm done", "that's all"
]

# Define timeout duration in seconds
TIMEOUT_DURATION = 300  # 5 minutes

# Define conversation states
class ConversationState(Enum):
    GREETING = auto()
    ASK_NAME = auto()
    COLLECTING_ORDER = auto()
    CONFIRMING_ORDER = auto()
    END = auto()

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
    print("\nAssistant: It seems you're no longer active. Feel free to reach out if you need anything else. Have a great day!")
    logging.info("Conversation timed out due to inactivity.")
    exit()

def load_data(file_path):
    if os.path.exists(file_path):
        with open(file_path, "r") as file:
            try:
                data = json.load(file)
                return data
            except json.JSONDecodeError:
                print(f"Warning: {file_path} is empty or contains invalid JSON. Initializing as empty.")
                return {}
    else:
        return {}

def save_data(file_path, data):
    with open(file_path, "w") as file:
        json.dump(data, file, indent=4)

def generate_order_id():
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
            new_id = 1  # Or handle as per your requirement

        new_id_str = f"{new_id:04d}"

        # Optional uniqueness check
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


def get_valid_phone_number():
    while True:
        phone_number = input("Assistant: Can I get your phone number please? (10 digits)\nYou: ")
        if re.match(r"^\d{10}$", phone_number):
            return phone_number
        else:
            print("Assistant: Please enter a 10-digit phone number without spaces or dashes.")
            

def get_order_details(user_input):
    """
    Parses user input to extract order details and prompts for missing information.
    Supports multiple pizzas, beverages, and extra items.
    """
    order = {
        "pizzas": [],
        "beverages": [],
        "extras": [],
        "delivery_method": None,  # Initialize as None
        "address": None
    }

    normalized_input = user_input.lower()

    # Extract pizza orders: e.g., "one large cheese pizza" or "1 large cheese pizza"
    pizza_pattern = r"(\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\b)\s+(small|medium|large)\s+([a-zA-Z\s]+)\s+pizzas?"
    pizza_matches = re.findall(pizza_pattern, normalized_input)

    number_words = {
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10
    }

    for quantity, size, toppings in pizza_matches:
        # Convert word numbers (e.g., "one") to integers
        quantity = number_words.get(quantity.lower(), quantity)  # Default to number if numeric
        order["pizzas"].append({
            "quantity": int(quantity),
            "size": size.capitalize(),
            "toppings": toppings.strip().title(),
            "extras": []  # Placeholder for additional options
        })

    # If no pizza orders are found, ask the user
    if not order["pizzas"]:
        while True:
            add_pizza = input("Assistant: What kind of pizza would you like? (e.g., 1 large cheese pizza)\nYou: ")
            pizza_match = re.match(pizza_pattern, add_pizza.lower())
            if pizza_match:
                quantity, size, toppings = pizza_match.groups()
                quantity = number_words.get(quantity.lower(), quantity)  # Convert word to number if needed
                order["pizzas"].append({
                    "quantity": int(quantity),
                    "size": size.capitalize(),
                    "toppings": toppings.strip().title(),
                    "extras": []  # Placeholder for additional options
                })
                break
            else:
                print("Assistant: Please provide a valid pizza order format (e.g., 1 large cheese pizza).")

    # Ask about extras for each pizza
    for pizza in order["pizzas"]:
        extra_question = f"Assistant: Would you like any extras for your {pizza['size']} pizza(s)? (e.g., extra cheese, garlic sauce)\nYou: "
        extras_response = input(extra_question).strip()
        if extras_response.lower() not in ["no", "none", "n/a"]:
            pizza["extras"] = [extra.strip().title() for extra in extras_response.split(",")]

    # Extract beverages dynamically based on user input
    beverage_pattern = r"(\b(?:one|two|three|four|five|six|seven|eight|nine|ten|\d+)\b)?\s*([a-zA-Z\s]+)"
    beverage_matches = re.findall(beverage_pattern, normalized_input)

    for quantity, item in beverage_matches:
        if "pizza" in item:  # Skip non-beverage items
            continue
        beverage_name = item.strip().title()
        quantity = number_words.get(quantity.lower(), quantity) if quantity else 1
        order["beverages"].append({
            "quantity": int(quantity),
            "item": beverage_name
        })

    # Check if beverages were already found in the input; skip redundant prompting
    if not order["beverages"]:
        add_beverages = input("Assistant: Would you like to add any beverages? (e.g., 2 cokes, 1 sprite)\nYou: ")
        if add_beverages.lower() not in ["no", "none", "n/a"]:
            additional_beverages = re.findall(beverage_pattern, add_beverages.lower())
            for quantity, item in additional_beverages:
                beverage_name = item.strip().title()
                quantity = number_words.get(quantity.lower(), quantity) if quantity else 1
                order["beverages"].append({
                    "quantity": int(quantity),
                    "item": beverage_name
                })

    # Ask for extras (e.g., sides, desserts)
    add_extras = input("Assistant: Would you like to add any extras? (e.g., garlic bread, brownies, dipping sauces)\nYou: ")
    if add_extras.lower() not in ["no", "none", "n/a"]:
        extras_list = [extra.strip().title() for extra in add_extras.split(",")]
        order["extras"] = extras_list

    # Determine delivery method from input or ask
    if "pickup" in normalized_input:
        order["delivery_method"] = "pickup"
    elif "delivery" in normalized_input:
        order["delivery_method"] = "delivery"

    if not order["delivery_method"]:
        while True:
            delivery_method = input("Assistant: Would you like delivery or pickup?\nYou: ").strip().lower()
            if delivery_method in ["delivery", "pickup"]:
                order["delivery_method"] = delivery_method
                break
            else:
                print("Assistant: Please specify either 'delivery' or 'pickup'.")

    # Get delivery address if necessary
    if order["delivery_method"] == "delivery" and not order["address"]:
        address = input("Assistant: Please provide your delivery address:\nYou: ")
        order["address"] = address.title()
    else:
        order["address"] = None

    return {
        "order_time": str(datetime.datetime.now()),
        "pizzas": order["pizzas"],
        "beverages": order["beverages"],
        "extras": order["extras"],
        "delivery_method": order["delivery_method"],
        "address": order["address"],
        "payment_method": None
    }


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

def is_negative_sentiment(user_input):
    analysis = TextBlob(user_input)
    # Adjust the threshold as needed
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
def handle_order(phone_number, customer_name, user_input, conversation_history, orders, customers):
    order_details = get_order_details(user_input)

    # Build the confirmation message
    assistant_response = "\nLet me confirm your order:\n"

    # List all pizzas
    for pizza in order_details["pizzas"]:
        assistant_response += f"- {pizza['quantity']} {pizza['size']} pizza(s) with {pizza['toppings']}\n"
        if pizza["extras"]:
            assistant_response += f"  Extras: {', '.join(pizza['extras'])}\n"

    # List all beverages
    for beverage in order_details["beverages"]:
        assistant_response += f"- {beverage['quantity']} {beverage['item']}\n"

    # List all extras
    if order_details["extras"]:
        assistant_response += f"- Extras: {', '.join(order_details['extras'])}\n"

    # Add delivery method
    assistant_response += f"- {order_details['delivery_method'].title()}"
    if order_details['address']:
        assistant_response += f"\n- Delivery to: {order_details['address']}"

    print(f"Assistant: {assistant_response}")
    conversation_history.append({"role": "assistant", "content": assistant_response})

    # Handle payment and confirmation as before
    assistant_response = "How would you like to pay? (cash/card)"
    print(f"Assistant: {assistant_response}")
    conversation_history.append({"role": "assistant", "content": assistant_response})

    payment_response = input("You: ").lower()
    conversation_history.append({"role": "user", "content": payment_response})

    if payment_response in ["card", "credit card"]:
        order_details["payment_method"] = "Card"
        assistant_response = "Alright, we'll charge it to your card."
    else:
        order_details["payment_method"] = "Cash"
        assistant_response = "We'll accept cash on delivery/pickup."
    print(f"Assistant: {assistant_response}")
    conversation_history.append({"role": "assistant", "content": assistant_response})

    # Final confirmation
    assistant_response = "\nWould you like to place this order? (yes/no)"
    print(f"Assistant: {assistant_response}")
    conversation_history.append({"role": "assistant", "content": assistant_response})

    confirmation = input("You: ").lower()
    conversation_history.append({"role": "user", "content": confirmation})

    if confirmation in ["yes", "y", "sure", "ok"]:
        order_id = generate_order_id()
        orders[order_id] = {
            "customer_name": customer_name,
            "phone_number": phone_number,
            "order_details": order_details,
            "status": "Received"
        }
        save_data(ORDERS_FILE, orders)
        customers[phone_number]["order_history"].append(order_id)
        save_data(CUSTOMERS_FILE, customers)

        assistant_response = f"Great! Your order is confirmed. Your order number is {order_id}"
        print(f"\nAssistant: {assistant_response}")
        conversation_history.append({"role": "assistant", "content": assistant_response})

        if order_details["delivery_method"] == "delivery":
            assistant_response = "We'll deliver it to you soon!"
        else:
            assistant_response = "It will be ready for pickup in about 20-25 minutes."
        print(assistant_response)
        conversation_history.append({"role": "assistant", "content": assistant_response})

        logging.info(f"Order placed by {customer_name} ({phone_number}): {order_details}")
    else:
        assistant_response = "No problem! Let me know if you'd like to make any changes or try something else."
        print(f"Assistant: {assistant_response}")
        conversation_history.append({"role": "assistant", "content": assistant_response})

def main_conversation():
    print("Assistant: Welcome to our Pizza Shop! How can I help you today?")

    global orders, customers
    orders = load_data(ORDERS_FILE)
    customers = load_data(CUSTOMERS_FILE)

    # Initialize conversation history with the greeting
    conversation_history = [{"role": "assistant", "content": "Welcome to our Pizza Shop! How can I help you today?"}]

    # Initialize and start the conversation timer
    conversation_timer = ConversationTimer(TIMEOUT_DURATION, on_timeout)
    conversation_timer.reset()

    current_state = ConversationState.GREETING

    while True:
        try:
            user_input = input("You: ")
            conversation_timer.reset()  # Reset timer on user input

            # Append user input to conversation history
            conversation_history.append({"role": "user", "content": user_input})

            # Check for exit phrases
            if any(phrase in user_input.lower() for phrase in EXIT_PHRASES):
                assistant_response = "Thanks for visiting! Have a great day!"
                print(f"Assistant: {assistant_response}")
                conversation_history.append({"role": "assistant", "content": assistant_response})
                break

            # Check for negative sentiment
            if is_negative_sentiment(user_input):
                assistant_response = "I'm sorry to hear that. If you need further assistance, feel free to ask!"
                print(f"Assistant: {assistant_response}")
                conversation_history.append({"role": "assistant", "content": assistant_response})
                continue

            # Check if user wants to end conversation
            if should_end_conversation(user_input):
                assistant_response = "Thanks for visiting! Have a great day!"
                print(f"Assistant: {assistant_response}")
                conversation_history.append({"role": "assistant", "content": assistant_response})
                break

            # Main logic: If user wants to order pizza
            if current_state == ConversationState.GREETING:
                if "order" in user_input.lower() or "pizza" in user_input.lower():
                    # Get phone number
                    phone_number = get_valid_phone_number()

                    if phone_number in customers:
                        name = customers[phone_number]["name"]
                        assistant_response = f"Welcome back, {name}!"
                        print(f"Assistant: {assistant_response}")
                        conversation_history.append({"role": "assistant", "content": assistant_response})
                    else:
                        assistant_response = "First time ordering with us? What's your name?"
                        print(f"Assistant: {assistant_response}")
                        conversation_history.append({"role": "assistant", "content": assistant_response})

                        name = input("You: ")
                        customers[phone_number] = {"name": name, "order_history": []}
                        save_data(CUSTOMERS_FILE, customers)

                        assistant_response = f"Nice to meet you, {name}!"
                        print(f"Assistant: {assistant_response}")
                        conversation_history.append({"role": "assistant", "content": assistant_response})

                    # Handle the order
                    handle_order(phone_number, name, user_input, conversation_history, orders, customers)
                    current_state = ConversationState.CONFIRMING_ORDER
                else:
                    # If user not asking for pizza or order
                    assistant_response = "I can help with ordering pizzas, just let me know what you'd like!"
                    print(f"Assistant: {assistant_response}")
                    conversation_history.append({"role": "assistant", "content": assistant_response})

            elif current_state == ConversationState.CONFIRMING_ORDER:
                assistant_response = "Anything else I can help you with?"
                print(f"Assistant: {assistant_response}")
                conversation_history.append({"role": "assistant", "content": assistant_response})
                # We remain in this state until user ends or starts another order

        except KeyboardInterrupt:
            assistant_response = "Conversation ended by user. Have a great day!"
            print(f"\nAssistant: {assistant_response}")
            conversation_history.append({"role": "assistant", "content": assistant_response})
            break
        except Exception as e:
            logging.error(f"Unexpected error: {e}")
            assistant_response = "Something went wrong. Please try again."
            print(f"Assistant: {assistant_response}")
            conversation_history.append({"role": "assistant", "content": assistant_response})

    # Cancel the timer when conversation ends
    conversation_timer.cancel()

if __name__ == "__main__":
    main_conversation()
