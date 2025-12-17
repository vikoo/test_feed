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

mutation_update_config_for_season = """
          mutation UpdateConfig($input: ConfigInput!) {
            updateConfig(data: $input) {
                data {
                    id
                    attributes {
                        driverTeamTrackSeasonTyre
                        driverStandingsForSeasonJson
                        teamStandingsForSeasonJson
                    }
                }
            }
          }
          """

mutation_update_config_for_gp = """
          mutation UpdateConfig($input: ConfigInput!) {
            updateConfig(data: $input) {
                data {
                    id
                    attributes {
                        grandPrixRace
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
            seasons(pagination: {limit: 50}) {
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

query_get_tracks = """
        query GetTracks {
            tracks(pagination: {limit: 50}) {
                data {
                    id
                    attributes {
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
                            }
                        }
                    }
                }
            }
        }
        """

mutation_post_season = """
        mutation PostSeason($input: SeasonInput!) {
            createSeason(data: $input) {
                data {
                    id
                }
            }
        }
        """

mutation_post_grand_prix = """
        mutation PostGrandPrix($input: GrandPrixInput!) {
            createGrandPrix(data: $input) {
                data {
                    id
                }
            }
        }
        """

mutation_post_race = """
        mutation PostRace($input: RaceInput!) {
            createRace(data: $input) {
                data {
                    id
                }
            }
        }
        """

mutation_update_race_with_time = """
          mutation UpdateRace($raceId: ID!,$startTime: DateTime!, $siteEventId: String!) {
                updateRace(
                    id: $raceId,
                    data: {
                        startTime: $startTime,
                        siteEventId: $siteEventId
                    }
                ) {
                    data {
                        id
                    }
                }
          }
          """


mutation_get_latest_past_race_entry = """
        query GetLatestRaceQuery($currentDate: DateTime!) {
            races(
                filters: {
                    startTime: {
                        lte: $currentDate
                    },
                },
                pagination: {
                    limit: 3
                }
                sort: "startTime:desc"
            ) {
                data {
                    id
                    attributes {
                        type
                        startTime
                        siteEventId
                        grandPrix {
                            data {
                                id
                                attributes {
                                    fullName
                                    shortName
                                    siteEventId
                                    season {
                                        data {
                                            id
                                            attributes {
                                                year
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
"""

query_race_results_for_race_event = """
        query GetRaceResults($raceId:ID!) {
            raceResults(
                filters: {
                    race: {
                        id: {
                            eq: $raceId
                        }
                    }
                },
                pagination: { limit: 30}
                sort: "position:asc"
            ) {
                data {
                    id
                }
            }
        }
"""

query_season_grid = """
        query GetSeasonGridQuery($season:String!) {
            seasonGrids(filters: { season: { year: { eq: $season} } }, pagination: {pageSize: 60}) {
                data {
                    id
                    attributes {
                        driverNumber
                        driver {
                            data {
                                id
                                attributes {
                                    number
                                }
                            }
                        }
                        isOldGrid
                    }
                }
            }
        }
"""

mutation_post_race_result = """
        mutation PostRaceResults($input: RaceResultInput!) {
            createRaceResult(data: $input) {
                data {
                    id
                }
            }
        }
"""

query_race_results_all = """
        query GetRacesForSeason($season: String!,$limit: Int, $start: Int) {
            raceResults(
                pagination: {
                    limit: $limit,
                    start: $start
                }
                filters: {
                    race: {
                        grandPrix: {
                            season: {
                                year: {
                                    eq: $season
                                }
                            }
                        }
                        type:{
                            in: ["Race", "Q3","Sprint","SQ3", "QNR1", "QNR2"]
                        }
                    }
                }
            ) {
                data {
                    id
                    attributes {
                        race {
                            data {
                                attributes {
                                    type
                                    grandPrix {
                                        data {
                                            id
                                            attributes {
                                                round
                                                name
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        seasonGrid {
                            data {
                                id
                                attributes {
                                    driver {
                                        data {
                                            id
                                            attributes {
                                                initials
                                            }
                                        }
                                    }
                                    chassis {
                                        data {
                                            attributes {
                                                team {
                                                    data {
                                                        id
                                                        attributes {
                                                            name
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        laps
                        points
                        time
                        position
                        finalPos
                        fastestLap
                        dnf
                        fantasyPts
                        sprintFinalPos
                        classification {
                            data {
                                id
                                attributes {
                                    type
                                }
                            }
                        }
                    }
                }
            }
        }
"""

query_driver_and_team_standings = """
       query GetDriverSeasonStats($season: String!) {
            driverStandings(
                filters: {
                    season: {
                        year: {
                            eq: $season
                        }
                    }
                },
                pagination: {
                    limit: 50
                }
            ) {
                data {
                    id
                    attributes {
                        season {
                            data {
                                id
                                attributes {
                                    year
                                }
                            }
                        }
                        seasonGrid {
                            data {
                                id
                                attributes {
                                    driver {
                                        data {
                                            id
                                            attributes {
                                                initials
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        position
                        points
                        raceWins
                        racePoles
                        sprintWins
                        sprintPoles
                        fastestLapsInRace
                        fastestLapsInSprint
                        biggestRaceWinMargins
                        avgPointsPerRace
                        avgPointsPerSprint
                        racePodiums
                        sprintPodiums
                        dnfInRace
                        dnfInSprint
                        avgRaceQualiPosition
                        avgSprintQualiPosition
                        avgRaceStartGridPosition
                        avgSprintStartGridPosition
                        avgRaceFinishPosition
                        avgSprintFinishPosition
                        avgRacePositionGained
                        avgSprintPositionGained
                        q3Appearances
                        sprintQ3Appearances
                        raceFirstRowStarts
                        sprintFirstRowStarts
                        top5FinishInRace
                        top10FinishInRace
                        top8FinishInSprint
                        noOfGPs
                        racePoints
                        sprintPoints
                        bestRaceFinish
                        bestSprintFinish
                        bestQualiPos
                        bestSprintQualiPos
                        grids {
                            data {
                                id
                                attributes {
                                    driver {
                                        data {
                                            id
                                            attributes {
                                                initials
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
            teamStandings(
                filters: {
                    season: {
                        year: {
                            eq: $season
                        }
                    }
                },
                pagination: {
                    limit: 50
                }
            ) {
                data {
                    id
                    attributes {
                        seasonGrid {
                            data {
                                id
                                attributes {
                                    driver {
                                        data {
                                            id
                                            attributes {
                                                initials
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        season {
                            data {
                                id
                                attributes {
                                    year
                                }
                            }
                        }
                        chassis {
                            data {
                                id
                                attributes {
                                    name
                                }
                            }
                        }
                        position
                        points
                        raceWins
                        racePoles
                        sprintWins
                        sprintPoles
                        fastestLapsInRace
                        fastestLapsInSprint
                        avgPointsPerRace
                        avgPointsPerSprint
                        racePodiums
                        sprintPodiums
                        dnfInSprint
                        dnfInRace
                        avgRaceQualiPosition
                        avgSprintQualiPosition
                        avgRaceStartGridPosition
                        avgSprintStartGridPosition
                        avgRaceFinishPosition
                        avgSprintFinishPosition
                        avgRacePositionGained
                        avgSprintPositionGained
                        q3Appearances
                        sprintQ3Appearances
                        raceFirstRowStarts
                        sprintFirstRowStarts
                        top5FinishInRace
                        top10FinishInRace
                        top8FinishInSprint
                        noOfGPs
                        racePoints
                        sprintPoints
                        bestRaceFinish
                        bestSprintFinish
                        bestQualiPos
                        bestSprintQualiPos
                    }
                }
            }
        } 
"""

mutation_update_driver_standing = """
        mutation UpdateDriverStanding($rowId: ID!, $driverStandingInput: DriverStandingInput!) {
            updateDriverStanding(id: $rowId, data: $driverStandingInput) {
                data {
                    id
                }
            }
        }
"""

mutation_update_team_standing = """
        mutation UpdateTeamStanding($rowId: ID!, $teamStandingInput: TeamStandingInput!) {
            updateTeamStanding(id: $rowId, data: $teamStandingInput) {
                data {
                    id
                }
            }
        }
"""