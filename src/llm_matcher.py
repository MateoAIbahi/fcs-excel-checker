import requests


LLM_URL = "http://icechat.ice.local/v1-devstral/chat/completions"
LLM_MODEL = "ollama/devstral-local"


def build_prompt(filename, available_tranches):
    tranches = "\n".join(f"- {t}" for t in available_tranches)

    return f"""
Tu dois associer un fichier Excel à une tranche FCS. Associe en fonction du nom, le nom de la tranche et le nom du fichier ne doivent pas être trop lointains l'un de l'autre.

Nom du fichier Excel :
{filename}

Tranches possibles :
{tranches}

Réponds uniquement avec le nom exact d'une tranche présente dans la liste.
Ne donne aucune explication.
Ne réponds pas en JSON.
Ne crée pas de nouvelle tranche.
""".strip()


def ask_llm_for_tranche(filename, available_tranches):
    prompt = build_prompt(filename, available_tranches)

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0
    }

    response = requests.post(LLM_URL, json=payload, timeout=30)
    response.raise_for_status()

    answer = response.json()["choices"][0]["message"]["content"].strip()

    for tranche in available_tranches:
        if answer == tranche:
            return tranche

    for tranche in available_tranches:
        if tranche in answer:
            return tranche

    return None