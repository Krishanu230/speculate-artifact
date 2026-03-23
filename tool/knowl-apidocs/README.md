## Using our generator

1. set the .env file in the knowl-apidocs folder.
2. use the following command to run the tool 'python gen_apidocs2.py ../../reviewapi/'
3. we can set the different models using: 
'python gen_apidocs2.py ../../reviewapi/ --spec-model gpt_4_1 --context-model gpt_4o_mini'
'python gen_apidocs2.py ../../reviewapi/ --spec-model gpt_4o_mini --context-model gpt_4o_mini'
'python gen_apidocs2.py ../../reviewapi/ --spec-model gemini-2.0-flash-001 --context-model gemini-2.0-flash-001'

we use simple names for open ai models as they hide the deployment info. but note that we use the full model names for the gemini models.
