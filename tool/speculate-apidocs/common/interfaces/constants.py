DRF_default_response_codes = {
    "GET_List": {
        "400": "Bad Request - Invalid query parameters.",
        "401": "Unauthorized - Authentication credentials were not provided.",
        "403": "Forbidden - User does not have permission to view the list.",
        "406": "Not Acceptable - Requested content type is not acceptable according to the Accept headers.",
    },
    "GET_Retrieve": {
        "400": "Bad Request - Invalid query parameters.",
        "401": "Unauthorized - Authentication credentials were not provided.",
        "403": "Forbidden - User does not have permission to view this object.",
        "404": "Not Found - Object with the given identifier does not exist.",
        "406": "Not Acceptable - Requested content type is not acceptable according to the Accept headers.",
    },
    "DELETE": {
        "400": "Bad Request - Bad input parameter.",
        "401": "Unauthorized - Authentication credentials were not provided.",
        "403": "Forbidden - User does not have permission to delete this object.",
        "404": "Not Found - Object to be deleted does not exist.",
        "405": "Method Not Allowed - DELETE method not allowed on the endpoint.",
        "429": "Too Many Requests - Too many requests; rate limit exceeded.",
    },
    "PATCH": {
        "400": "Bad Request - Bad input, validation error, or partial update not allowed.",
        "401": "Unauthorized - Authentication credentials were not provided.",
        "403": "Forbidden - User does not have permission to edit this object.",
        "404": "Not Found - Object to be updated does not exist.",
        "405": "Method Not Allowed - PATCH method not allowed on the endpoint.",
        "406": "Not Acceptable - Requested content type is not acceptable.",
        "415": "Unsupported Media Type - Unsupported media type in request.",
        "429": "Too Many Requests - Too many requests; rate limit exceeded.",
    },
    "POST": {
        "400": "Bad Request - Bad input, validation error.",
        "401": "Unauthorized - Authentication credentials were not provided.",
        "403": "Forbidden - User does not have permission to create the object.",
        "404": "Not Found - URL not found.",
        "405": "Method Not Allowed - POST method not allowed on the endpoint.",
        "406": "Not Acceptable - Requested content type is not acceptable.",
        "415": "Unsupported Media Type - Unsupported media type in request.",
        "429": "Too Many Requests - Too many requests; rate limit exceeded.",
    },
}

# For the request and response prompts the last 6 steps are same.

# Each point from now on just avoids certain scenarios. For example asking it to not give components section, not give "null" as a type,
# Asking it to make sure syntax of output is correct etc.
path_section_common_prompt = """
                    4. While deciding the types of each field make sure you adhere to the standard primitive types of openAPI.
                    5. DO NOT add the x-codeSamples section to the openAPI definition.
                    6. DO NOT create the component section of openAPI definition. 
                    7. In the end return ONLY the openAPI definition.
                    8. DO NOT reference($ref) a serializer which isn't mentioned in the code.
                    9. Use all your knowledge about the rules of openAPI specifications 3.0, python DRF and your best analytical ability and quantitative aptitude.
                    10. Make sure your output STRICTLY conforms to openAPI specifications 3.0 and is a 100 percent syntactically correct YAML.
                    11. For each example and description subsection write the text inside double-quotes.

                    NOTE: Analyse the code carefully. The way that the code is written could vary significantly from standard ways of writing APIs in DRF. Hence, rigorously analyse the code.
                    """
