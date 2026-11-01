"""Types of business. The key is stored; the label is shown. Add new ones at the end."""
from typing import Literal

SECTORS: dict[str, str] = {
    "retail": "Retail shop / duka",
    "wholesale": "Wholesale / distributor",
    "service": "Other services",
    "food": "Food, hotel or restaurant",
    "agri": "Farming and agribusiness",
    "manufacturing": "Manufacturing or processing",
    "beauty": "Salon, barber or beauty",
    "fashion": "Clothes, tailoring or shoes",
    "hardware": "Hardware and building materials",
    "electronics": "Phones, electronics or repairs",
    "agent": "M-Pesa agent or money services",
    "transport": "Transport, boda boda or logistics",
    "health": "Chemist, pharmacy or clinic",
    "education": "School, tuition or training",
    "ict": "Cyber cafe, printing or ICT",
    "other": "Something else",
}

Sector = Literal["retail", "wholesale", "service", "food", "agri", "manufacturing", "beauty", "fashion",
                 "hardware", "electronics", "agent", "transport", "health", "education", "ict", "other"]

assert set(Sector.__args__) == set(SECTORS)  # keep the two lists in step
