# Tamwini Load Testing via Locust

## Prepare sample data
Provided is a script `generate_households.py` that would generate the test data needed for locust.
It should be run against the SCOPE instance to be tested.

```
python generate_households.py --office lb-co --households 220000 --apply-changes
```
The command above will generate 220000 households for `lb-co`

Once the script has finished execution, it will create `households.csv` containing the test data. It will also print on
console output the necessary ids and tokens for the locust script.

```
# sample output
External App Secret: ELGATZTEXNQY45LJ
External App UUID: 0aa13373-f018-4c81-ab64-e231755be6e6
API user token: api-user-token
Company token: example-company-token
```


## Setup locust

Once we have the sample data ready, we can create the env file that locust will use.
Create a copy of `sample.env` and rename it to `locust.env`

Copy the contents of the output above after the household generation script to the env file.
```
TAMWINI_EXT_APP_SECRET_KEY=ELGATZTEXNQY45LJ
TAMWINI_EXT_APP_UUID=0aa13373-f018-4c81-ab64-e231755be6e6
API_USER_TOKEN=api-user-token
COMPANY_TOKEN=example-company-token
```

Copy the generated `households.csv` into `data` directory.


Build the locust docker image by running
```
./build.sh
```

Run the locust environment
```
docker compose up --build
```

To run with multiple workers
```
docker compose up --build --scale worker=4
```

Open the locust web page on http://localhost:8089
