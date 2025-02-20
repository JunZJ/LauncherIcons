import concurrent.futures
import json
import logging
import os

import requests

from PIL import Image
import io


logging.basicConfig(level=logging.INFO)
session = requests.Session()


def merge_apps(existing_apps, new_apps):
    logging.info("Merging existing and new apps...")
    existing_packages = {app['packageName'] for app in existing_apps}
    merged_data = []
    for new_app in new_apps:
        package_name = new_app["packageName"]
        if package_name in existing_packages:
            app_data = {
                "appName": new_app.get("appName", ""),
                "packageName": package_name,
                "id": new_app.get("id", "")
            }
            merged_data.append(app_data)
        else:
            logging.info(f"MISSING:\n{{appName: {new_app.get('appName', '')}, packageName: {package_name}, id: {new_app.get('id', '')}}}")
            merged_data.append(new_app)
    return merged_data


pico_headers = {
    "User-Agent": "AssistantPhone 1.2.2 rv:1.2.2.02 (iPad; iPadOS 17.0; en_DE) Cronet"
    }


def fetch_pico_apps(existing_apps):
    logging.info("Fetching Pico apps...")

    pico_options = {
        "url": "https://appstore-us.picovr.com/api/app/v1/section/info",
        "method": "POST",
        "params": {
            "manifest_version_code": "300800000",
            "app_language": "en",
            "size": "20",
            "device_name": "A8110",
            "page": "1",
            "section_id": "3",
        },
    }

    def fetch_apps():
        nonlocal page, has_more, app_data
        pico_options["params"]["page"] = str(page)

        logging.info(f"Fetching Pico apps from page {page}")

        response = session.request(**pico_options, headers=pico_headers)
        response_data = response.json()

        if "data" in response_data and response_data["data"] and "items" in response_data["data"]:
            new_apps = [
                dict(
                    app,
                    appName=app.get("name", ""),
                    packageName=app.get("package_name", ""),
                    id=app.get("item_id", ""),
                )
                for app in response_data["data"]["items"]
                if app.get("package_name")
            ]

            app_data.extend(new_apps)
            has_more = response_data["data"].get("has_more", False)

            if has_more:
                page += 1
                fetch_apps()
        else:
            logging.error("No data found in the response.")
            has_more = False

    page = 1
    has_more = True
    app_data = []

    fetch_apps()

    merged_data = merge_apps(existing_apps, app_data)

    with open("pico_apps.json", "w") as f:
        json.dump(merged_data, f)

    logging.info("Pico apps fetched successfully.")
    return merged_data


def fetch_oculus_apps(existing_apps):
    logging.info("Fetching Oculus apps...")
    oculus_options = {
        "url": "https://oculusdb.rui2015.me/api/v1/allapps",
        "method": "GET",
    }

    response = session.request(**oculus_options)
    data = response.json()

    new_apps = [
        dict(
            app,
            appName=app.get("appName", ""),
            packageName=app.get("packageName", ""),
            id=app.get("id", ""),
        )
        for app in data
        if app.get("packageName") and "rift" not in app.get("packageName")
    ]
    app_data = merge_apps(existing_apps, new_apps)

    # Write the updated data to the oculus_apps.json file
    with open("oculus_apps.json", "w") as f:
        json.dump(app_data, f)

    logging.info("Oculus apps fetched successfully.")


def fetch_oculus_apps_with_covers(existing_apps):
    logging.info("Fetching Oculus apps...")

    section_ids = ["1888816384764129", "174868819587665"]

    landscape_folder = "oculus_landscape"
    portrait_folder = "oculus_portrait"
    square_folder = "oculus_square"

    os.makedirs(landscape_folder, exist_ok=True)
    os.makedirs(portrait_folder, exist_ok=True)
    os.makedirs(square_folder, exist_ok=True)

    new_apps = []

    with concurrent.futures.ThreadPoolExecutor() as executor:
        for section_id in section_ids:
            items_api_url = f"https://graph.oculus.com/graphql?forced_locale=en_US&doc_id=4743589559102018&access_token=OC|1076686279105243|&variables={{\"sectionId\":\"{section_id}\",\"sortOrder\":null,\"sectionItemCount\":1000}}"

            response = session.get(items_api_url)
            response_data = response.json()

            edges = response_data['data']['node']['all_items']['edges']

            for edge in edges:
                node = edge['node']
                app_details_api_url = f"https://graph.oculus.com/graphql?access_token=OC|1076686279105243|&doc_id=3828663700542720&variables={{\"applicationID\":\"{node['id']}\"}}"

                try:
                    app_details_response = session.get(app_details_api_url)
                    app_details_data = app_details_response.json()
                    latest_supported_binary = app_details_data['data']['node']['release_channels']['nodes'][0]['latest_supported_binary']

                    if latest_supported_binary is not None:
                        app_binary_info_api_url = f"https://graph.oculus.com/graphql?doc=query ($params: AppBinaryInfoArgs!) {{ app_binary_info(args: $params) {{ info {{ binary {{ ... on AndroidBinary {{ id package_name version_code asset_files {{ edges {{ node {{ ... on AssetFile {{ file_name uri size }} }} }} }} }} }} }} }} }}&variables={{\"params\":{{\"app_params\":[{{\"app_id\":\"{node['id']}\",\"version_code\":\"{latest_supported_binary['version_code']}\"}}]}}}}&access_token=OC|1317831034909742|"

                        app_binary_info_response = session.get(app_binary_info_api_url)
                        app_binary_info_data = app_binary_info_response.json()
                        package_name = app_binary_info_data['data']['app_binary_info']['info'][0]['binary']['package_name']
                        display_name = node['display_name']

                        landscape_url = node['cover_landscape_image']['uri']
                        portrait_url = node['cover_portrait_image']['uri']
                        square_url = node['cover_square_image']['uri']

                        executor.submit(download_image, landscape_url, os.path.join(landscape_folder, f"{package_name}.jpg"))
                        executor.submit(download_image, portrait_url, os.path.join(portrait_folder, f"{package_name}.jpg"))
                        executor.submit(download_image, square_url, os.path.join(square_folder, f"{package_name}.jpg"))

                        logging.info(f"Downloaded images for {package_name}")

                        new_apps.append({
                            "appName": display_name,
                            "packageName": package_name,
                            "id": node['id']
                        })

                except Exception as error:
                    logging.error(f"Error: {error}")

    merged_apps = merge_apps(existing_apps, new_apps)

    # Write the updated data to the oculus_apps.json file
    with open("oculus_apps.json", "w") as f:
        json.dump(merged_apps, f)

    logging.info("Oculus apps fetched successfully.")


def download_image(url, filename):
    with requests.get(url, stream=True) as response:
        response.raise_for_status()
        with open(filename, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)


def fetch_pico_covers(app_data):
    logging.info("Fetching Pico app covers...")
    if not os.path.exists("pico_square"):
        os.makedirs("pico_square")
    if not os.path.exists("pico_landscape"):
        os.makedirs("pico_landscape")

    urls = [
        f"https://appstore-us.picovr.com/api/app/v1/item/info?app_language=en&device_name=A8110&item_id={app['id']}&manifest_version_code=300800000"
        for app in app_data
    ]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        square_filenames = []
        landscape_filenames = []
        futures = []
        for url in urls:
            futures.append(executor.submit(session.post, url, headers=pico_headers))

        for future, app in zip(futures, app_data):
            try:
                response = future.result()
                response.raise_for_status()
                data = response.json()
                square_url = data["data"]["cover"]["square"]
                landscape_url = data["data"]["cover"]["landscape"]
                square_filename = f"pico_square/{app['packageName']}.png"
                landscape_filename = f"pico_landscape/{app['packageName']}.png"
                square_filenames.append(square_filename)
                landscape_filenames.append(landscape_filename)
                executor.submit(download_image, square_url, square_filename)
                executor.submit(download_image, landscape_url, landscape_filename)
                logging.info(f"Downloading Covers for {app['packageName']}")
            except Exception as e:
                error_msg = f"Error: {str(e)}\n"
                with open("pico_cover_errors.log", "a") as f:
                    f.write(error_msg + "\n")
                logging.error(error_msg)
                continue

    logging.info("All Pico app covers downloaded.")

def download_image_webp(url, filename):
    with requests.get(url, stream=True) as response:
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content))
        # Convert and save the image in webp format
        image.save(filename, 'WEBP')

def fetch_viveport_covers(existing_apps):
    logging.info("Fetching Viveport app covers...")

    # Folders for different thumbnail sizes
    small_folder = "viveport_small"
    medium_folder = "viveport_medium"
    large_folder = "viveport_large"
    square_folder = "viveport_square"

    os.makedirs(small_folder, exist_ok=True)
    os.makedirs(medium_folder, exist_ok=True)
    os.makedirs(large_folder, exist_ok=True)
    os.makedirs(square_folder, exist_ok=True)

    # GraphQL query and variables
    graphql_query = '''
    query getProduct(
    $category_id: String
    $app_type: [String]
    $prod_type: [String]
    $pageSize: Int
    $currentPage: Int
    ) {
    products(
        filter: {
        category_id: { eq: $category_id }
        app_type: { in: $app_type }
        prod_type: { in: $prod_type }
        }
        pageSize: $pageSize
        currentPage: $currentPage
    ) {
        total_count
        page_info {
        total_pages
        }
        items {
        sku
        }
    }
    }
    '''

    graphql_variables = {
        "category_id": 277,
        "app_type": [
            "5"
        ],
        "prod_type": [
            "375",
            "377"
        ],
        "pageSize": 9999,
        "currentPage": 1
    }

    graphql_url = "https://www.viveport.com/graphql"
    headers = {"Content-Type": "application/json"}

    # Fetch app IDs
    app_ids = []
    while True:
        response = session.post(graphql_url, json={"query": graphql_query, "variables": graphql_variables}, headers=headers)
        response_data = response.json()

        app_ids += [item["sku"] for item in response_data["data"]["products"]["items"]]

        logging.info(f"Fetched app IDs from page {graphql_variables['currentPage']} of {response_data['data']['products']['page_info']['total_pages']}")

        total_pages = response_data["data"]["products"]["page_info"]["total_pages"]
        if graphql_variables["currentPage"] >= total_pages:
            break

        graphql_variables["currentPage"] += 1

    # Fetch and download app covers
    new_apps = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        for app_id in app_ids:
            try:
                post_data = {
                    "app_ids": [app_id],
                    "show_coming_soon": True,
                    "content_genus": "all",
                    "subscription_only": 1,
                    "include_unpublished": True
                }
                response = session.post("https://www.viveport.com/api/cms/v4/mobiles/a", json=post_data)
                response_data = response.json()

                app_data = response_data["contents"][0]["apps"][0]
                package_name = app_data["package_name"]
                app_name = app_data["title"]
                thumbnails = app_data["thumbnails"]

                executor.submit(download_image_webp, thumbnails["small"]["url"], os.path.join(small_folder, f"{package_name}.webp"))
                executor.submit(download_image_webp, thumbnails["medium"]["url"], os.path.join(medium_folder, f"{package_name}.webp"))
                executor.submit(download_image_webp, thumbnails["large"]["url"], os.path.join(large_folder, f"{package_name}.webp"))
                executor.submit(download_image_webp, thumbnails["square"]["url"], os.path.join(square_folder, f"{package_name}.webp"))

                logging.info(f"Downloaded images for {package_name}")

                new_apps.append({
                    "appName": app_name,
                    "id": app_id,
                    "packageName": package_name,
                    "id": app_id
                })
            except Exception as error:
                logging.error(f"Error: {error}")

    merged_apps = merge_apps(existing_apps, new_apps)

    with open("viveport_apps.json", "w") as f:
        json.dump(merged_apps, f)

    logging.info("Done fetching Viveport app covers.")


def fetch_vive_business_covers(existing_apps):
    logging.info("Fetching Vive Business app covers...")

    # Folders for different thumbnail sizes
    small_folder = "vive_business_small"
    medium_folder = "vive_business_medium"
    large_folder = "vive_business_large"
    square_folder = "vive_business_square"

    os.makedirs(small_folder, exist_ok=True)
    os.makedirs(medium_folder, exist_ok=True)
    os.makedirs(large_folder, exist_ok=True)
    os.makedirs(square_folder, exist_ok=True)

    # GraphQL query and variables
    graphql_query = '''
    query getProductAll($pageSize: Int, $currentPage: Int) {
      products(filter: {}, pageSize: $pageSize, currentPage: $currentPage) {
        total_count
        page_info {
          total_pages
        }
        items {
          sku
          deviceType
        }
        __typename
      }
    }
    '''

    graphql_variables = {
        "pageSize": 9999,
        "currentPage": 1
    }

    graphql_url = "https://business.vive.com/graphql"
    headers = {"Content-Type": "application/json"}

    # Fetch app IDs
    app_ids = []
    while True:
        response = requests.post(graphql_url, json={"query": graphql_query, "variables": graphql_variables}, headers=headers)
        response_data = response.json()

        app_ids += [item["sku"] for item in response_data["data"]["products"]["items"] if item['deviceType'] == '1_']

        logging.info(f"Fetched app IDs from page {graphql_variables['currentPage']} of {response_data['data']['products']['page_info']['total_pages']}")

        total_pages = response_data["data"]["products"]["page_info"]["total_pages"]
        if graphql_variables["currentPage"] >= total_pages:
            break

        graphql_variables["currentPage"] += 1

    # Fetch and download app covers
    new_apps = []
    with concurrent.futures.ThreadPoolExecutor() as executor:
        for app_id in app_ids:
            try:
                post_data = {
                    "app_ids": [app_id],
                    "product_type": 5,
                    "cnty": "US"
                }

                response = requests.post("https://business.vive.com/api/cms/v4/mobiles/a", json=post_data)
                response_data = response.json()

                app_data = response_data["contents"][0]["apps"][0]
                package_name = app_data["package_name"]
                app_name = app_data["title"]
                thumbnails = app_data["thumbnails"]

                executor.submit(download_image_webp, thumbnails["small"]["url"], os.path.join(small_folder, f"{package_name}.webp"))
                executor.submit(download_image_webp, thumbnails["medium"]["url"], os.path.join(medium_folder, f"{package_name}.webp"))
                executor.submit(download_image_webp, thumbnails["large"]["url"], os.path.join(large_folder, f"{package_name}.webp"))
                executor.submit(download_image_webp, thumbnails["square"]["url"], os.path.join(square_folder, f"{package_name}.webp"))

                logging.info(f"Downloaded images for {package_name}")

                new_apps.append({
                    "appName": app_name,
                    "id": app_id,
                    "packageName": package_name,
                    "id": app_id
                })
            except Exception as error:
                logging.error(f"Error: {error}")

    merged_apps = merge_apps(existing_apps, new_apps)

    with open("vive_business_apps.json", "w") as f:
        json.dump(merged_apps, f)

    logging.info("Done fetching Vive Business app covers.")


if __name__ == "__main__":
    try:
        with open("pico_apps.json") as f:
            existing_pico_apps = json.load(f)
    except FileNotFoundError:
        existing_pico_apps = []

    app_data = fetch_pico_apps(existing_pico_apps)
    fetch_pico_covers(app_data)

    try:
        with open("oculus_apps.json") as f:
            existing_oculus_apps = json.load(f)
    except FileNotFoundError:
        existing_oculus_apps = []

    fetch_oculus_apps_with_covers(existing_oculus_apps)

    try:
        with open("viveport_apps.json") as f:
            existing_viveport_apps = json.load(f)
    except FileNotFoundError:
        existing_viveport_apps = []

    fetch_viveport_covers(existing_viveport_apps)

    try:
        with open("vive_business_apps.json") as f:
            existing_vive_business_apps = json.load(f)
    except FileNotFoundError:
        existing_vive_business_apps = []

    fetch_vive_business_covers(existing_vive_business_apps)
