ALTER USER postgres WITH PASSWORD 'dB$A5Be?&^5q';

CREATE DATABASE eva_db;

\c eva_db;

CREATE TABLE eva_data(
    address         varchar     NOT NULL, 
    zip             char(4)     NOT NULL, 
    city            varchar     NOT NULL, 
    canton          varchar(2), 
    price_chf       int         NOT NULL, 
    rooms           varchar     NOT NULL, 
    area_m2         int,
    floor           varchar, 
    utilities_chf   int, 
    date_available  date, 
    date_scraped    date        NOT NULL,
    date_last_seen  date        NOT NULL,
    url             varchar     NOT NULL
);

CREATE TABLE eva_prices(
    url         varchar     NOT NULL,
    date        date        NOT NULL,
    price_chf   int         NOT NULL
);
