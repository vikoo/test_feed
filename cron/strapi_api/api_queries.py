query_get_config = """
          {
            config {
                data {
                    id
                    attributes {
                        driverStandingsForSeasonJson
                        teamStandingsForSeasonJson
                        raceResultFastestLapForGrandPrixJson
                        driverTeamTrackSeasonTyre
                        grandPrixRace
                        chassisSeasonGrid
                        imageFromServer
                        apiFromServer
                        feedJson
                    }
                }
            }
          }
          """

mutation_update_config_for_feeds = """
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
        mutation PostFeed($input: FeedInput!, $locale: I18NLocaleCode) {
            createFeed(data: $input, locale: $locale) {
                data {
                    id
                }
            }
        }
        """

mutation_update_feed = """
        mutation UpdateFeed($feedId: ID!, $input: FeedInput!, $locale: I18NLocaleCode) {
            updateFeed(id: $feedId, data: $input, locale: $locale) {
                data {
                    id
                }
            }
        }
"""
query_old_feeds = """
        query GetOldFeeds($cutoffDate: DateTime!, $limit: Int!, $start: Int!, $locale: I18NLocaleCode) {
              feeds(
                    filters: { pubDate: { lte: $cutoffDate } }
                    pagination: { limit: $limit, start: $start }
                    sort: ["pubDate:asc", "id:asc"],
                    locale: $locale
              ) {
                    data {
                        id
                    }
              }
        }
"""
query_old_votes = """
        query GetOldVotes($cutoffDate: DateTime!, $limit: Int!, $start: Int!) {
            votes(
                filters: { updatedAt: { lte: $cutoffDate } }
                pagination: { limit: $limit, start: $start }
                sort: ["updatedAt:asc", "id:asc"]
            ) {
                data {
                    id
                }
            }
        }
"""

query_old_vote_counts = """
        query GetOldVoteCounts($cutoffDate: DateTime!, $limit: Int!, $start: Int!) {
            voteCounts(
                filters: { updatedAt: { lte: $cutoffDate } }
                pagination: { limit: $limit, start: $start }
                sort: ["updatedAt:asc", "id:asc"]
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

mutation_delete_vote = """
        mutation DeleteVote($id: ID!) {
            deleteVote(id: $id) {
                data {
                    id
                }
            }
        }
"""

mutation_delete_vote_count = """
        mutation DeleteVoteCount($id: ID!) {
            deleteVoteCount(id: $id) {
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
                    endDate: {
                        gte: $currentDate
                    }
                },
                type: {
                    notIn: ["FP1","FP2","FP3","Q2","Q3","SQ2","SQ3"]
                }
            },
            pagination: {
                limit: 5
            }
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

query_get_seasons = """
        query GetSeasons {
            seasons {
                data {
                    id
                    attributes {
                        year
                        name
                    }
                }
            }
        }
        """

query_get_grand_prixes_for_year = """
        query GetGrandPrixRacesQuery($season:String!) {
            grandPrixes(filters: { season: { year: { eq: $season} } }, sort: "startDate:asc", pagination: {limit: 100}) {
                data {
                    id
                    attributes {
                        name
                        fullName
                        shortName
                        startDate
                        endDate
                        length
                        distance
                        laps
                        round
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
                                }
                            }
                        }
                    }
                }
            }
            races(filters: { grandPrix: {season: { year: { eq: $season} } } }, sort: "startTime:asc", pagination: {limit: 500}) {
                data {
                    id
                    attributes {
                        identifier
                        startTime
                        type
                        highlights
                        grandPrix {
                            data {
                                id
                                attributes {
                                    name
                                    fullName
                                    shortName
                                }
                            }
                        }
                    }
                }
            }
        }
        """