import os
from dotenv import load_dotenv
from groq import Groq

# Load environment variables from .env
load_dotenv()

api_key = os.getenv("GROQ_API_KEY")
if not api_key:
    raise ValueError("GROQ_API_KEY not found in environment or .env file.")

client = Groq(api_key=api_key)

response = client.chat.completions.create(
    messages=[
        {
            "role": "user",
            "content": "Hello world",
        }
    ],
    model="llama-3.3-70b-versatile",
)

print(response.choices[0].message.content)
