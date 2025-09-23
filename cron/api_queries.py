query_get_config = """
          {
            config {
                data {
                    id
                    attributes {
                        feedJson
                    }
                }
            }
          }
          """

mutation_update_config = """
          mutation UpdateConfig($input: ConfigInput!) {
            updateConfig(data: $input) {
                data {
                    id
                    attributes {
                        feedJson
                    }
                }
            }
          }
          """

mutation_post_feed = """
        mutation PostFeed($input: FeedInput!) {
            createFeed(data: $input) {
                data {
                    id
                }
            }
        }
        """
query_old_feeds = """
        query GetOldFeeds($cutoffDate: DateTime!, $limit: Int!, $start: Int!) {
              feeds(
                    filters: { pubDate: { lte: $cutoffDate } }
                    pagination: { limit: $limit, start: $start }
                    sort: "pubDate:asc"
              ) {
                    data {
                        id
                    }
              }
        }
"""
mutation_delete_feed = """
        mutation DeleteFeed($id: ID!) {
            deleteFeed(id: $id) {
                data {
                    id
                }
            }
        }
"""

query_get_latest_grand_prixes = """
    query GetLatestGrandPrixQuery($currentDate: DateTime!) {
        grandPrixes(
            filters: {
                endDate: {
                    gte: $currentDate
                }
            }
            pagination: {
                limit: 1
            }
            sort: "startDate:asc"
        ) {
            data {
                id
                attributes {
                    name
                    startDate
                    fullName
                    endDate
                    round
                    season {
                        data {
                            attributes {
                                year
                            }
                        }
                    }
                    track {
                        data {
                            id
                            attributes {
                                name
                                imageOutline
                                image
                                imageFancy
                                city
                                country
                                latitude
                                longitude
                            }
                        }
                    }
                }
            }
        }
        races(
            filters: {
                grandPrix: {
                    startDate: {
                        lte: $currentDate
                    },
                    endDate: {
                        gte: $currentDate
                    }
                },
                type: {
                    notIn: ["FP1","FP2","FP3","Q2","Q3","SQ2","SQ3"]
                }
            },
            sort: "startTime"
        ) {
            data {
                id
                attributes {
                    type
                    startTime
                    grandPrix {
                        data {
                            id
                        }
                    }
                    weather {
                        data {
                            id
                        }
                    }
                }
            }
        }
    }
    """

mutation_post_weather = """
        mutation PostWeather($input: WeatherInput!) {
            createWeather(data: $input) {
                data {
                    id
                }
            }
        }
        """

mutation_update_weather = """
        mutation UpdateWeather($id: ID!, $input: WeatherInput!) {
            updateWeather(
                id: $id,
                data: $input
            ) {
                data {
                    id
                }
            }
        }
        """

mutation_update_race_with_weather = """
        mutation UpdateRace($raceId: ID!, $weatherId: ID!) {
            updateRace(
                id: $raceId,
                data: {weather: $weatherId}
            ) {
                data {
                    id
                }
            }
        }
        """