
def get_title_body_for_notification(grand_prix, race_type):
    gp_id = grand_prix["id"]
    gp_name = grand_prix["attributes"]["name"]
    gp_name =remove_year(gp_name)
    gp_track = grand_prix["attributes"]["track"]["data"]["attributes"]["name"]
    gp_country = grand_prix["attributes"]["track"]["data"]["attributes"]["country"]
    print(f"grand_prix: {gp_name} at {gp_track} (id: {gp_id}), race type: {race_type}, country: {gp_country}")
    return __get_final_title_body_for_notification(gp_name, race_type)


def remove_year(text: str) -> str:
    return text.rsplit(" ", 1)[0]

def __get_final_title_body_for_notification(gp_name, race_type):
    title =  gp_name + ": " + race_type + " Results Out!"
    body = f"Check out the complete results for the {race_type} now."
    return title, body
