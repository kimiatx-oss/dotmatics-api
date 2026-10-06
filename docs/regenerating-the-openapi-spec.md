# Export your Inventory API description

No vendor-authored OpenAPI description is bundled with this project. With your
own authorized account, request `GET /inventory/api/docs` on your deployment,
or use `inventory._get('docs')` on an authenticated `Inventory` instance.

Save and consult the result locally according to your license and deployment
policies. It may include instance hostnames and configuration details. Do not
commit the exported description or response into this repository. The method
above is an internal convenience; the HTTP endpoint is the underlying operation.
