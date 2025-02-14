from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Set, Tuple
import json
from datetime import datetime
import os
import uuid
from pymongo import MongoClient
from dotenv import load_dotenv
import phonenumbers

# Load environment variables
load_dotenv()

app = FastAPI(root_path="/upload_contacts")

# MongoDB setup
MONGO_URI = os.getenv("MONGODB_URI")  # MongoDB URI from environment variable   
client = MongoClient(MONGO_URI)
db = client.get_database()  # Automatically uses 'wp_automation' from the URI
contacts_collection = db["contacts"]  # Collection will be created automatically when inserting data

# Storage directory setup
STORAGE_DIR = "contact_storage"
os.makedirs(STORAGE_DIR, exist_ok=True)

# Data model for incoming contact data
class ContactData(BaseModel):
    data: Any  # Expects a 'data' field with JSON structure

def cleanup_phone_numbers(phones: list) -> list:
    """Clean up phone numbers and remove duplicates while preserving order"""
    seen = set()
    cleaned_phones = []
    
    for phone in phones:
        try:
            # If number doesn't start with +, assume it's Indian
            region = None if phone.strip().startswith('+') else 'IN'
            # Parse phone number
            parsed = phonenumbers.parse(phone, region)
            # Format to standard international format
            formatted = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
            
            if formatted not in seen:
                seen.add(formatted)
                cleaned_phones.append(formatted)
        except phonenumbers.NumberParseException:
            # If parsing fails, keep original number if not already seen
            if phone not in seen:
                seen.add(phone)
                cleaned_phones.append(phone)
    
    return cleaned_phones

def cleanup_emails(emails: list) -> list:
    """Clean up emails and remove duplicates while preserving order"""
    seen = set()
    cleaned_emails = []
    
    for email in emails:
        # Basic email cleanup: lowercase and strip whitespace
        cleaned_email = email.lower().strip()
        if cleaned_email not in seen:
            seen.add(cleaned_email)
            cleaned_emails.append(cleaned_email)
    
    return cleaned_emails

def get_unique_contacts_count() -> Tuple[int, Set[str]]:
    """
    Count unique contacts and return their phone numbers.
    A contact is unique if none of their phone numbers exist in previous contacts.
    """
    unique_count = 0
    all_phones = set()
    
    
    # Get all contacts with at least one phone number
    contacts = contacts_collection.find(
        {"phones": {"$exists": True, "$ne": []}}
    )
    
    for contact in contacts:
        contact_phones = set(contact.get("phones", []))
        
        # Check if any phone number exists in our set
        if not contact_phones.intersection(all_phones):
            unique_count += 1
        
        # Add all phone numbers to set regardless
        all_phones.update(contact_phones)
    
    return unique_count, all_phones

@app.get("/")
async def root():
    return {
        "status": "success",
        "message": "running",
    }

@app.post("/save-contacts")
async def save_contacts(contact_data: ContactData):
    try:
        # Add debug logging
#        print("Received contact data:", contact_data.dict())
        
        # Generate unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"contacts_{timestamp}.json"
        os.makedirs(STORAGE_DIR, exist_ok=True) 
        # Clean up contacts data
        contacts = contact_data.data.get("contacts", [])
        for contact in contacts:
            contact["phones"] = cleanup_phone_numbers(contact.get("phones", []))
            contact["emails"] = cleanup_emails(contact.get("emails", []))

        reference_name = contact_data.data.get("userName", "unknown")
        
        # Save the cleaned data to a JSON file with reference name
        final_filename = f"{reference_name}-contacts_{timestamp}.json"
        final_path = os.path.join(STORAGE_DIR, final_filename)
        with open(final_path, "w") as f:
            json.dump(contact_data.data, f, indent=4)

        # Insert each contact
        for contact in contacts:
            contact_doc = {
                "_id": str(uuid.uuid4()),
                "reference_name": reference_name,
                "name": contact.get("name", ""),
                "firstName": contact.get("firstName", ""),
                "phones": contact.get("phones", []),
                "emails": contact.get("emails", []),
                "created_at": datetime.utcnow()
            }
            contacts_collection.insert_one(contact_doc)

        return {
            "status": "success",
            "message": "success",
            "filename": filename,
            "data": contact_data.data
        }

    except Exception as e:
        # Log error to file with timestamp
        error_message = f"[{datetime.now().isoformat()}] Error saving contacts: {str(e)}\n"
        with open("error.txt", "a") as error_file:  # Creates file if not exists
            error_file.write(error_message)
            
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "message": "error",
                "timestamp": datetime.now().isoformat()
            }
        )

# Endpoint to list saved contact files
@app.get("/list-contacts")
async def list_contacts():
    try:
        files = os.listdir(STORAGE_DIR)
        return {
            "status": "success",
            "files": files
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Endpoint to read a specific contact file
@app.get("/read-contacts/{filename}")
async def read_contacts(filename: str):
    try:
        file_path = os.path.join(STORAGE_DIR, filename)
        with open(file_path, "r") as f:
            data = json.load(f)
        return {
            "status": "success",
            "data": data
        }
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Add this new endpoint after other endpoints
@app.get("/count-unique-contacts")
async def count_unique_contacts():
    try:
        count, _ = get_unique_contacts_count()
        return {
            "status": "success",
            "unique_contacts": count
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={
                "status": "error",
                "message": str(e),
                "timestamp": datetime.now().isoformat()
             }
        )