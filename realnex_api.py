from real_nex_sync_api_data_facade.sdk import RealNexSyncApiDataFacade

def upload_data_to_realnex(data, company_id):
    try:
        client = RealNexSyncApiDataFacade(api_key="your-api-key")  # Replace with actual token
        response = client.upload_data(data, company_id)
        return response
    except Exception as e:
        return {"error": str(e)}
