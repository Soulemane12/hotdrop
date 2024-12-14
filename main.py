import openai
import os
import json
from dotenv import load_dotenv
import uuid
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

ORDERS_FILE = "orders1.json"
CUSTOMERS_FILE = "customers1.json"

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
    return str(uuid.uuid4())

def get_valid_phone_number():
    while True:
        phone_number = input("Assistant: Can I get your phone number please? (10 digits)\nYou: ")
        if re.match(r"^\d{10}$", phone_number):
            return phone_number
        else:
            print("Assistant: Please enter a 10-digit phone number without spaces or dashes.")

def get_order_details(user_input):
    """
    Parses user input to extract order details using regular expressions.
    """
    order = {}

    # Extract pizza size
    size_match = re.search(r"\b(small|medium|large)\b", user_input.lower())
    if size_match:
        order["size"] = size_match.group(1).capitalize()
    else:
        order["size"] = "Medium"  # Default if not mentioned

    # Extract toppings
    # If user mentioned something like "cheese pizza" we try to pick that up
    # Otherwise default to "Cheese"
    if "cheese" in user_input.lower():
        order["toppings"] = "Cheese"
    else:
        # Try to extract after the word "pizza" if mentioned
        toppings_match = re.search(r"pizza with (.+)$", user_input.lower())
        if toppings_match:
            order["toppings"] = toppings_match.group(1).strip().title()
        else:
            order["toppings"] = "Cheese"

    # Extract quantity if mentioned (e.g. "3 pizzas")
    quantity_match = re.search(r"\b(\d+)\s+pizzas?\b", user_input.lower())
    if quantity_match:
        order["quantity"] = int(quantity_match.group(1))
    else:
        order["quantity"] = 1

    # Extract delivery method
    if "delivery" in user_input.lower():
        order["delivery_method"] = "delivery"
    elif "pickup" in user_input.lower():
        order["delivery_method"] = "pickup"
    else:
        order["delivery_method"] = "pickup"  # Default if not mentioned

    # Extract address if delivery
    if order.get("delivery_method") == "delivery":
        address_match = re.search(r"address:\s*(.+)", user_input.lower())
        if address_match:
            order["address"] = address_match.group(1).strip().title()
        else:
            # If not provided in the initial input, will ask later
            order["address"] = None
    else:
        order["address"] = None

    return {
        "order_time": str(datetime.datetime.now()),
        "pizza": {
            "quantity": order["quantity"],
            "size": order["size"],
            "toppings": order["toppings"]
        },
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

    # If address not found and delivery is chosen, ask now
    if order_details["delivery_method"] == "delivery" and order_details["address"] is None:
        address = input("Assistant: What is your delivery address?\nYou: ")
        order_details["address"] = address.title()
        conversation_history.append({"role": "user", "content": address})

    # Confirm order details
    assistant_response = f"\nLet me confirm your order:\n- {order_details['pizza']['quantity']} {order_details['pizza']['size']} pizza(s) with {order_details['pizza']['toppings']}\n- {order_details['delivery_method'].title()}"
    if order_details['address']:
        assistant_response += f"\n- Delivery to: {order_details['address']}"
    print(f"Assistant: {assistant_response}")
    conversation_history.append({"role": "assistant", "content": assistant_response})

    # Suggest upsell
    upsell = suggest_upsells(order_details)
    if upsell:
        assistant_response = f"\nWould you like to add {upsell}? (yes/no)"
        print(f"Assistant: {assistant_response}")
        conversation_history.append({"role": "assistant", "content": assistant_response})

        upsell_response = input("You: ").lower()
        conversation_history.append({"role": "user", "content": upsell_response})

        if upsell_response in ["yes", "y", "sure", "ok"]:
            order_details["extras"] = upsell
            assistant_response = "Added to your order!"
            print(f"Assistant: {assistant_response}")
            conversation_history.append({"role": "assistant", "content": assistant_response})

    # Ask for payment method
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
