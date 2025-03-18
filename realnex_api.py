from real_nex_sync_api_data_facade.sdk import RealNexSyncApiDataFacade

def upload_data_to_realnex(data, user_token):
    try:
        client = RealNexSyncApiDataFacade(api_key=user_token)  # User enters their token
        response = client.upload_data(data)
        return response
    except Exception as e:
        return {"error": str(e)}
