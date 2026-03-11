import google.generativeai as genai
import os
from dotenv import load_dotenv
load_dotenv()

key = os.getenv('GEMINI_API_KEY')
print('Key found:', 'YES' if key else 'NO')
print('Key starts with:', key[:10] if key else 'NONE')

genai.configure(api_key=key)
model = genai.GenerativeModel('gemini-1.5-flash')
response = model.generate_content('Say hello in one word')
print('Gemini response:', response.text)
