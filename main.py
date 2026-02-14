from fastapi import FastAPI, Request, Response
import uvicorn
import google.generativeai as genai
from supabase import create_client
import httpx
import os
import json
from dotenv import load_dotenv

# Load secrets from .env file
load_dotenv()

app = FastAPI()

# Configuration
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
VERIFY_TOKEN = os.getenv("VERIFY_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Initialize Clients
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-2.0-flash')
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.get("/")
async def home():
    return {"status": "Kharchaa Bot is Alive!"}

@app.get("/webhook")
async def verify_webhook(request: Request):
    """Verifies webhook for WhatsApp"""
    hub_mode = request.query_params.get("hub.mode")
    hub_challenge = request.query_params.get("hub.challenge")
    hub_verify_token = request.query_params.get("hub.verify_token")
    
    if hub_verify_token == VERIFY_TOKEN:
        return int(hub_challenge)
    return Response(content="Forbidden", status_code=403)

@app.post("/webhook")
async def receive_message(request: Request):
    try:
        data = await request.json()
        
        # Check if it's a message from user
        entry = data.get('entry', [])[0]
        changes = entry.get('changes', [])[0]
        value = changes.get('value', {})
        
        if 'messages' in value:
            message = value['messages'][0]
            user_phone = message['from']
            msg_body = message.get('text', {}).get('body', '')
            
            # Skip if empty
            if not msg_body:
                return "OK"

            # 1. AI Extraction
            prompt = f"""
            Extract transaction details from this text (Indian context).
            Text: "{msg_body}"
            Return ONLY a raw JSON string (no markdown formatting) with these keys:
            - amount (number)
            - merchant (string)
            - category (string - Food, Travel, Bills, Shopping, Other)
            
            If it's not a transaction, return {{"error": "not_transaction"}}
            """
            
            ai_response = model.generate_content(prompt)
            cleaned_text = ai_response.text.replace('```json', '').replace('```', '').strip()
            extracted_data = json.loads(cleaned_text)
            
            if "error" not in extracted_data:
                # 2. Save to Supabase
                supabase.table('expenses').insert({
                    "user_phone": user_phone,
                    "amount": extracted_data['amount'],
                    "merchant": extracted_data['merchant'],
                    "category": extracted_data['category'],
                    "raw_text": msg_body
                }).execute()
                
                # 3. Reply to User
                reply_text = f"✅ Recorded ₹{extracted_data['amount']} for {extracted_data['merchant']} ({extracted_data['category']})"
                send_whatsapp_msg(user_phone, reply_text)
            else:
                # Optional: Reply if AI didn't understand
                # send_whatsapp_msg(user_phone, "I didn't catch that. Try: 'Paid 50 for Tea'")
                pass
                
    except Exception as e:
        print(f"Error: {e}")
        
    return "OK"

def send_whatsapp_msg(to, text):
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    httpx.post(url, json=payload, headers=headers)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)