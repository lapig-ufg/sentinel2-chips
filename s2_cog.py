import os
import tempfile
from datetime import datetime

import cv2
import numpy as np
import pytz
import ray
from dynaconf import Dynaconf
from loguru import logger
from osgeo import gdal, osr
from pymongo import MongoClient
from satsearch import Search
from shapely.geometry import mapping, shape

settings = Dynaconf(
    envvar_prefix='LAPIG',
    settings_files=[
        'settings.toml',
        '.secrets.toml',
    ],
    environments=True,
    load_dotenv=True,
)


# logger.add("s2_cog.log", rotation="10 GB",  mode="a")

BANDS = ['nir', 'swir16', 'red']

SATELLITES = ['L8', 'L7', 'L5']

PERIODS_BR = [
    {'name': 'WET', 'dtStart': '-01-01', 'dtEnd': '-04-30'},
    {'name': 'DRY', 'dtStart': '-06-01', 'dtEnd': '-10-30'},
]

campaign = None

ray.init()


class Constants:
    STAC_API_URL = 'https://earth-search.aws.element84.com/v1'
    COLLECTION = 'sentinel-2-l2a'
    CLOUD_COVER_LIMIT = 5


# def adjust_gamma(image, gamma=0.5):
#     inv_gamma = 1.0 / gamma
#     table = np.array([((i / 255.0) ** inv_gamma) * 255
#                       for i in np.arange(0, 256)]).astype("uint8")

#     return cv2.LUT(image, table)


# def enhance_img(data):
#     r, g, b = cv2.split(data)

#     clahe_small = cv2.createCLAHE(clipLimit=4.0, tileGridSize=(8, 8))
#     clahe_big = cv2.createCLAHE(clipLimit=10.0, tileGridSize=(8, 8))

#     rl = clahe_big.apply(r)
#     gl = clahe_small.apply(g)
#     bl = clahe_big.apply(b)
#     limg = cv2.merge((rl, gl, bl))
#     limg = adjust_gamma(limg, 1.5)

#     return limg


def adjust_gamma(image, gamma=0.5):
    inv_gamma = 1.0 / gamma
    table = np.array(
        [((i / 255.0) ** inv_gamma) * 255 for i in np.arange(0, 256)]
    ).astype('uint8')
    return cv2.LUT(image, table)


def enhance_img(data):
    r, g, b = cv2.split(data)

    # Use milder CLAHE settings for JPEG
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    r = clahe.apply(r)
    g = clahe.apply(g)
    b = clahe.apply(b)

    limg = cv2.merge((r, g, b))
    limg = adjust_gamma(limg, 2.5)

    # Optional: Apply mild noise reduction to reduce JPEG artifacts
    # limg = cv2.fastNlMeansDenoisingColored(limg, None, 10, 10, 7, 21)

    return limg


# def read_img(filename):
#     return cv2.imread(filename)


# def enhance_img_clahe(image_path):
#     data1 = read_img(image_path)
#     data1 = enhance_img(data1)
#     write_img(image_path, data1)


# def write_img(filename, data):
#     cv2.imwrite(filename, data)


def read_img(filename):
    return cv2.imread(filename)


def write_img(filename, data):
    cv2.imwrite(filename, data)


def enhance_img_clahe(image_path):
    data = read_img(image_path)
    data = enhance_img(data)
    write_img(image_path, data)


@logger.catch
def get_linear_scale(ds, band_index):
    band = ds.GetRasterBand(band_index)
    band_array = band.ReadAsArray()
    min_val = np.min(band_array)
    max_val = np.max(band_array)
    return min_val, max_val


@logger.catch
def extract_chip(
    id,
    vrt_path,
    lon,
    lat,
    output_cog,
    item,
    buffer=4000,
    width=1024,
    height=1024,
):
    try:

        # TVI_IMAGES_PATH = os.environ.get('STORAGE_DIR_PATH')
        TVI_IMAGES_PATH = settings.STORAGE_DIR_PATH
        index, campaign = id.split('_', 1)
        dir_path = f'{TVI_IMAGES_PATH}/{campaign}/{id}'
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

        ds = gdal.Open(vrt_path)

        # Extract the dataset's projection
        inSpatialRef = osr.SpatialReference()
        inSpatialRef.ImportFromWkt(ds.GetProjectionRef())

        outSpatialRef = osr.SpatialReference()
        outSpatialRef.ImportFromEPSG(4674)

        # Set up the transformation
        transform = osr.CoordinateTransformation(outSpatialRef, inSpatialRef)
        x, y, _ = transform.TransformPoint(lat, lon)

        x_res = buffer / (width / 2)  # or buffer*2 / width
        y_res = buffer / (height / 2)  # or buffer*2 / height

        half_width = width * x_res / 2
        half_height = height * y_res / 2
        ulx = x - half_width
        uly = y + half_height
        lrx = x + half_width
        lry = y - half_height

        item['bbox'] = [ulx, uly, lrx, lry]

        # logger.info(f"VRT: {vrt_path} | {lon} {lat} | BBOX: {ulx} {uly} {lrx} {lry}")
        # scale_params = [[600, 5400, 1, 255], [700, 4300, 1, 255], [400, 2800, 1, 255]],
        # scale_params = [[700, 4300, 1, 255], [600, 5400, 1, 255], [400, 2800, 1, 255]],
        scale_params = [
            [1900, 4500, 1, 255],
            [1500, 5000, 1, 255],
            [350, 2000, 1, 255],
        ]

        options = gdal.TranslateOptions(
            format='JPEG',
            xRes=x_res,
            yRes=y_res,
            outputType=gdal.GDT_Byte,
            creationOptions=['WORLDFILE=YES'],
            scaleParams=scale_params,
            projWin=[ulx, uly, lrx, lry],
        )
        img_path = f'{dir_path}/{output_cog}'
        gdal.Translate(img_path, ds, options=options)
        enhance_img_clahe(img_path)
        ds = None
        # logger.info(item)
        return item
    except Exception as e:
        logger.error(e)
        pass


@logger.catch
def create_vrt(id, urls, output_name, lon, lat, item):
    try:
        separate = True
        if len(urls) == 1:
            separate = False

        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.vrt')
        vrt_path = tmp_file.name
        tmp_file.close()

        options = gdal.BuildVRTOptions(separate=separate)
        gdal.BuildVRT(vrt_path, urls, options=options)

        # Create the chip PNG for the given point
        output_png = f'{output_name}.jpg'
        return extract_chip(id, vrt_path, lon, lat, output_png, item)
    except Exception as e:
        logger.error(e)
        pass


@logger.catch
def get_best_image_by_period(year, items):
    try:
        result = {}

        if year > 2012:
            satellite = 'L8'
        elif year > 2011:
            satellite = 'L7'
        elif year > 2003 or year < 2000:
            satellite = 'L5'
        else:
            satellite = 'L7'

        for period_dict in PERIODS_BR:
            period = period_dict['name']
            dt_start = f"{year}{period_dict['dtStart']}"
            dt_end = f"{year}{period_dict['dtEnd']}"

            # Convert string dates to datetime
            dt_start_date = datetime.strptime(dt_start, '%Y-%m-%d')
            dt_end_date = datetime.strptime(dt_end, '%Y-%m-%d')
            aware_dt_start_date = pytz.utc.localize(dt_start_date)
            aware_dt_end_date = pytz.utc.localize(dt_end_date)

            period_items = [
                item
                for item in items
                if isinstance(item.datetime, datetime)
                and aware_dt_start_date <= item.datetime <= aware_dt_end_date
            ]
            # If there are items for this period, get the one with the least cloud cover
            if period_items:
                best_item = min(
                    period_items,
                    key=lambda item: item.properties['eo:cloud_cover'],
                )

                # Store the result
                index = f'{satellite}_{year}_{period}'
                result[index] = {
                    'image_index': index,
                    'image': best_item,
                    'datetime': best_item.datetime,
                    'bbox': None,
                }

        return result
    except Exception as e:
        logger.error(e)
        pass


@logger.catch
@ray.remote
def process_year(id, year, geometry, lon, lat):
    try:

        start_date = datetime(year, 1, 1, 0, 0, 0).isoformat() + 'Z'
        end_date = datetime(year + 1, 1, 1, 0, 0, 0).isoformat() + 'Z'

        date_range = f'{start_date}/{end_date}'

        search = Search(
            url=Constants.STAC_API_URL,
            intersects=mapping(geometry),
            datetime=date_range,
            collections=[Constants.COLLECTION],
            query={'eo:cloud_cover': {'lt': Constants.CLOUD_COVER_LIMIT}},
            limit=1000,
        )

        items = sorted(
            search.items(), key=lambda item: item.properties['eo:cloud_cover']
        )

        items_dict = get_best_image_by_period(year, items)
        if items:
            results = []
            for property, item in items_dict.items():
                urls = [
                    f"/vsicurl/{item['image'].assets[b]['href']}"
                    for b in BANDS
                ]
                composite_name = f'{property}'.upper()
                results.append(
                    create_vrt(id, urls, composite_name, lon, lat, item)
                )

            return results
        else:
            return None
    except Exception as e:
        logger.exception(e)
        pass


@logger.catch
def execute(years_range, points_collection):
    for point in points_collection:
        try:
            tasks = []
            geometry = {
                'type': 'Point',
                'coordinates': [point['lon'], point['lat']],
            }
            logger.info(geometry)
            point_id = point['_id']
            geom = shape(geometry)
            if geom.type != 'Point':
                logger.error('Geometry is not a Point.')
                continue

            lon, lat = geom.x, geom.y
            for year in years_range:
                tasks.append(
                    process_year.remote(point_id, year, geom, lon, lat)
                )

            # Wait for all tasks to complete
            results = ray.get(tasks)
            if results is not None:
                flat_results = [
                    item for sublist in results for item in sublist
                ]
                flat_results = [
                    {k: v for k, v in item.items() if k != 'image'}
                    for item in flat_results
                ]
                images = sorted(
                    flat_results,
                    key=lambda r: r['datetime']
                    if r is not None
                    else datetime.min,
                )
                db.points.update_one(
                    {'_id': point['_id']},
                    {'$set': {'images': images, 'cached': True}},
                )

                logger.info(f"Point {point['_id']} finished!")
            else:
                logger.warning(
                    f"Point {point['_id']} not generated! Results: {results}"
                )
                db.points.update_one(
                    {'_id': point['_id']},
                    {
                        '$set': {
                            'cached': False,
                            'error': f"Point {point['_id']} not generated ! Results: {results}",
                        }
                    },
                )

        except Exception as e:
            db.points.update_one(
                {'_id': point['_id']},
                {'$set': {'cached': False, 'error': str(e)}},
            )
            logger.error(
                f"Point {point['_id']} not generated! Results: {results} | Error {str(e)}"
            )
            pass


try:
    # client = MongoClient(os.environ.get('MONGO_HOST'), int(os.environ.get('MONGO_PORT')))
    client = MongoClient(settings.MONGO_HOST, settings.MONGO_PORT)

    db = client.tvi

    campaign = db.campaign.find_one({'_id': 'sicredi_ms_pastagem'})
    # points = list(db.points.find(
    #     {
    #         "campaign": campaign["_id"],
    #         "index": {
    #             "$gt": 2679,
    #             "$lt": 2697
    #         }
    #     }
    # ))
    points = list(
        db.points.find({'campaign': campaign['_id'], 'cached': False})
    )
    years = range(campaign['initialYear'], campaign['finalYear'] + 1)

    execute(years, points)

except Exception as e:
    logger.exception(e)
    pass
