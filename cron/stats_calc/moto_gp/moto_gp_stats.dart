import 'package:fimber/fimber.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:get_it/get_it.dart';
import 'package:ps_data_flutter/model/race_result.dart';
import 'package:ps_data_flutter/model/season_item.dart';
import 'package:ps_data_flutter/modules/graphql/schema/getDriverSeasonStats.graphql.dart';
import 'package:ps_data_flutter/modules/graphql/schema/getRacesForSeason.graphql.dart';
import 'package:ps_data_flutter/modules/graphql/schema/schema.graphql.dart';
import 'package:ps_data_flutter/repo/strapi/strapi_api_repo.dart';
import 'package:ps_data_flutter/screens/f1/stats/stats_update_bloc.dart';
import 'package:ps_data_flutter/screens/motogp/motogp_stats/motogp_stats_update_state.dart';
import 'package:ps_data_flutter/utils/common_utils.dart';
import 'package:ps_data_flutter/utils/moto_gp_race_utils.dart';

class MotogpStatsUpdateBloc extends Cubit<MotogpStatsUpdateState> {
  var strapiRepo = GetIt.instance.get<StrapiApiRepo>();

  MotogpStatsUpdateBloc() : super(const StatsUpdateInitial()) {
    init();
  }

  init() {
    _fetchSeasons();
  }

  Future<void> _fetchSeasons() async {
    var seasonItems = await strapiRepo.fetchSeasons(CommonUtils.MOTOGP_CLIENT);
    if (seasonItems.isNotEmpty) {
      emit(SeasonsFetched(seasonItems));
    }
  }

  Future<void> updateStats(SeasonItem season) async {
    Fimber.i("## updateStats: ${season.title}");

    List<Query$GetRacesForSeason$raceResults$data> allRaceResults =
        await strapiRepo.getAllRaceResults(CommonUtils.MOTOGP_CLIENT, season.title);

    // fetching driver standings and team standings
    var standingsResponse = await strapiRepo.getStandingsForStats(CommonUtils.MOTOGP_CLIENT, season.title);

    Map<String?, Map<String, dynamic>> driverSeasonGridIdToStatsMap = {};
    Map<String?, Map<String, dynamic>> teamIdToStatsMap = {};

    if (standingsResponse.first.isNotEmpty) {
      List<Pair<Query$GetDriverSeasonStats$driverStandings$data, List<String?>>> standingsWithMultipleGrids = [];
      Map<String?, Map<String, dynamic>> driverMultiSeasonGridIdToStatsMap = {};
      // driver standings
      for (var driverStanding in standingsResponse.first) {
        // Fimber.i("## driverStanding: ${driverStanding.toJson()}");
        if (driverStanding.id == null) {
          Fimber.i("## driverStanding: driver id null");
          continue;
        }
        var standingsId = driverStanding.id;
        var driverSeasonGridId = driverStanding.attributes?.seasonGrid?.data?.id;
        Fimber.i("## standingsId: $standingsId - driverSeasonGridId: $driverSeasonGridId");
        var raceResults =
        allRaceResults.where((element) => element.attributes?.seasonGrid?.data?.id == driverSeasonGridId).toList();
        driverSeasonGridIdToStatsMap[driverSeasonGridId] =
            populateDriverData(standingsId, driverSeasonGridId, raceResults, driverStanding.attributes?.position ?? 0);

        // if driver is part of multiple teams, here standings has multiple grids as driver is part of multiple teams
        if (driverStanding.attributes?.grids != null && driverStanding.attributes!.grids!.data.isNotEmpty) {
          Fimber.i("## standingsId: $standingsId - driverSeasonGridId: $driverSeasonGridId -> has multiple grids");
          List<String?> gridIds = [];
          for (var grid in driverStanding.attributes!.grids!.data) {
            var gridId = grid.id;
            gridIds.add(gridId);
            // dont get the data for primary grid id as its already done in previous step
            if (gridId != driverSeasonGridId) {
              Fimber.i("GRIDS member driverStanding: gridId: $gridId");
              var gridRaceResults =
              allRaceResults.where((element) => element.attributes?.seasonGrid?.data?.id == gridId).toList();
              // this map will be helpful in team stats data
              driverSeasonGridIdToStatsMap[gridId] = populateDriverData(
                  standingsId, gridId, gridRaceResults, driverStanding.attributes?.position ?? 0,
                  isPrimaryGridId: false);
            } else {
              Fimber.i("GRIDS primary driverStanding: gridId: $gridId NOT calculating data");
            }
          }
          standingsWithMultipleGrids.add(Pair(driverStanding, gridIds));
        }
      }

      // fetch the stats for same driver but multi grid
      if (standingsWithMultipleGrids.isNotEmpty) {
        Fimber.i("standingsWithMultipleGrids: ${standingsWithMultipleGrids.length}");
        for (var standingsWithGrids in standingsWithMultipleGrids) {
          Fimber.i("standingsWithMultipleGrids collecting for standingsId: ${standingsWithGrids.first.id}");
          var standings = standingsWithGrids.first;
          var gridIds = standingsWithGrids.second;
          Fimber.i("standingsWithMultipleGrids gridIds: $gridIds");
          var multiDriverRaceResults =
          allRaceResults.where((element) => gridIds.contains(element.attributes?.seasonGrid?.data?.id)).toList();
          var stats = populateDriverData(standings.id, "", multiDriverRaceResults, standings.attributes?.position ?? 0,
              isTeam: true);
          var driverSeasonPrimaryGridId = standings.attributes?.seasonGrid?.data?.id;
          driverMultiSeasonGridIdToStatsMap[driverSeasonPrimaryGridId] = stats;
        }
      }

      // sort position
      List<Map<String, dynamic>> driversList = [];
      for (var driverStanding in standingsResponse.first) {
        var driverSeasonGridId = driverStanding.attributes?.seasonGrid?.data?.id;
        // if season grid contains multiple grids, then we need to get the data from driverMultiSeasonGridIdToStatsMap
        // else we can get the data from driverSeasonGridIdToStatsMap
        if (driverMultiSeasonGridIdToStatsMap[driverSeasonGridId] != null) {
          Fimber.i("adding multi GRIDS driverStanding to list: gridId: $driverSeasonGridId");
          driversList.add(driverMultiSeasonGridIdToStatsMap[driverSeasonGridId]!);
        } else {
          Fimber.i("adding single driverStanding: gridId to list: gridId: $driverSeasonGridId");
          driversList.add(driverSeasonGridIdToStatsMap[driverSeasonGridId]!);
        }
      }
      driversList.sort((a, b) {
        int cmp = b[RaceResult.POINTS].compareTo(a[RaceResult.POINTS]);
        if (cmp != 0) {
          return cmp;
        } else {
          int cmpBestFinish = a['bestRaceFinish'].compareTo(b['bestRaceFinish']);
          if (cmpBestFinish != 0) {
            return cmpBestFinish;
          }
        }
        return a[RaceResult.POSITION].compareTo(b[RaceResult.POSITION]);
      });
      for (var i = 0; i < driversList.length; i++) {
        driversList[i][RaceResult.POSITION] = i + 1;

        // upload the data for primary grid is driver standings only
        if (driversList[i]['is_primary_grid_id'] == true) {
          Fimber.i("uploading for primary grid id: ${driversList[i]['driver_season_grid_id']}");
          var input = Input$DriverStandingInput.fromJson(driversList[i]);
          await strapiRepo.updateDriverStandings(CommonUtils.MOTOGP_CLIENT, input, driversList[i]['standings_id']);
        } else {
          Fimber.i("skip upload for non primary grid id: ${driversList[i]['driver_season_grid_id']}");
        }
      }


      // ------- TEAM STANDINGS
      for (var teamStanding in standingsResponse.second) {
        var seasonGrids = teamStanding.attributes?.seasonGrid?.data;
        var teamId = teamStanding.id;
        List<String> driverIDList = [];
        var avgPointsPerRace = 0.0;
        var avgPointsPerSprint = 0.0;
        for (var seasonGrid in seasonGrids ?? []) {
          driverIDList.add(seasonGrid.id);
          // driver map is already filled while calculating driver standings stats
          var map = driverSeasonGridIdToStatsMap[seasonGrid.id];
          if (map == null) {
            Fimber.i(
                "********** driverMap: null for ${seasonGrid.id} : team: ${teamStanding.attributes?.chassis?.data?.attributes?.name}");
            continue;
          }
          avgPointsPerRace += map['avgPointsPerRace'];
          avgPointsPerSprint += map['avgPointsPerSprint'];
        }
        var teamRaceResults =
            allRaceResults.where((element) => driverIDList.contains(element.attributes?.seasonGrid?.data?.id)).toList();
        teamIdToStatsMap[teamId] =
            populateDriverData(teamId, "", teamRaceResults, teamStanding.attributes?.position ?? 0, isTeam: true);
        teamIdToStatsMap[teamId]?['avgPointsPerRace'] = avgPointsPerRace;
        teamIdToStatsMap[teamId]?['avgPointsPerSprint'] = avgPointsPerSprint;
      }

      // sort position
      var teamsList = teamIdToStatsMap.values.toList();
      teamsList.sort((a, b) {
        int cmp = b[RaceResult.POINTS].compareTo(a[RaceResult.POINTS]);
        if (cmp != 0) {
          return cmp;
        }
        return a[RaceResult.POSITION].compareTo(b[RaceResult.POSITION]);
      });

      for (int i = 0; i < teamsList.length; i++) {
        teamsList[i][RaceResult.POSITION] = i + 1;
        var input = Input$TeamStandingInput.fromJson(teamsList[i]);
        await strapiRepo.updateTeamStandings(CommonUtils.MOTOGP_CLIENT, input, teamsList[i]['standings_id']);
      }
      await _updateConfig(season.title);
    }

    emit(MoveToHome());
  }

  Map<String, dynamic> populateDriverData(String? standingId, String? driverSeasonGridId,
      List<Query$GetRacesForSeason$raceResults$data> raceResults, int position,
      {bool isTeam = false, isPrimaryGridId = true}) {
    Map<String, dynamic> map = {};

    void populateRaceData(
        String type,
        String pointsKey,
        String avgPointsKey,
        String winsKey,
        String podiumsKey,
        String topFinishKey,
        String fastestLapsKey,
        String dnfKey,
        String bestFinishKey,
        String avgFinishKey,
        int topFinishLimit,
        String? top5FinishKey) {
      var races = raceResults.where((element) => element.attributes?.race?.data?.attributes?.type == type).toList();
      map[pointsKey] = races.fold(0.0, (sum, race) => sum + (race.attributes?.points ?? 0.0));
      map[avgPointsKey] = races.isNotEmpty ? map[pointsKey] / races.length : 0;
      map[winsKey] = races.where((race) => (race.attributes?.finalPos ?? race.attributes?.position) == 1).length;
      map[podiumsKey] = races
          .where((race) =>
              (race.attributes?.finalPos ?? race.attributes?.position) != null &&
              (race.attributes?.finalPos ?? race.attributes?.position)! <= 3)
          .length;
      if (top5FinishKey != null) {
        map[top5FinishKey] = races
            .where((race) =>
                (race.attributes?.finalPos ?? race.attributes?.position) != null &&
                (race.attributes?.finalPos ?? race.attributes?.position)! <= 5)
            .length;
      }
      map[topFinishKey] = races
          .where((race) =>
              (race.attributes?.finalPos ?? race.attributes?.position) != null &&
              (race.attributes?.finalPos ?? race.attributes?.position)! <= topFinishLimit)
          .length;
      map[fastestLapsKey] = races.where((race) => race.attributes?.fastestLap == true).length;
      map[dnfKey] = races
          .where(
              (race) => race.attributes?.dnf == true || race.attributes?.classification?.data?.attributes?.type != null)
          .length;
      var positions = races
          .map((race) => race.attributes?.finalPos ?? race.attributes?.position)
          .where((pos) => pos != null)
          .cast<int>();
      map[bestFinishKey] = positions.isNotEmpty ? positions.reduce((a, b) => a < b ? a : b) : 0;
      var sumOfPositions = positions.fold(0.0, (sum, position) => sum + (position));
      map[avgFinishKey] = positions.isNotEmpty ? sumOfPositions / races.length : -999;
    }

    populateRaceData(
        MotoGpRaceUtils.MOTO_RACE_RACE,
        'racePoints',
        'avgPointsPerRace',
        'raceWins',
        'racePodiums',
        'top10FinishInRace',
        'fastestLapsInRace',
        'dnfInRace',
        'bestRaceFinish',
        'avgRaceFinishPosition',
        10,
        'top5FinishInRace');

    populateRaceData(
        MotoGpRaceUtils.MOTO_RACE_SPRINT,
        'sprintPoints',
        'avgPointsPerSprint',
        'sprintWins',
        'sprintPodiums',
        'top8FinishInSprint',
        'fastestLapsInSprint',
        'dnfInSprint',
        'bestSprintFinish',
        'avgSprintFinishPosition',
        8,
        null);
    map['points'] = map['racePoints'] + map['sprintPoints'];

    void populateQualiData(
        String polesKey,
        String firstRowStartsKey,
        String q3AppearancesKey,
        String bestQualiPosKey,
        String avgQualiPosKey,
        String avgStartGridPosKey,
        String avgPositionGainedKey,
        String avgFinishPosKey,
        bool isSprint) {
      var qnr1 = raceResults
          .where((element) => element.attributes?.race?.data?.attributes?.type == MotoGpRaceUtils.MOTO_RACE_QUALI1)
          .toList();
      // +10 in qnr1 position
      qnr1 =
          qnr1.where((element) => element.attributes!.position != null && element.attributes!.position! > 2).toList();
      List<Query$GetRacesForSeason$raceResults$data> qnr1ForQuali = [];
      qnr1.forEach((element) {
        var json = element.toJson();
        json['attributes']['position'] = (element.attributes!.position! + 10);
        qnr1ForQuali.add(Query$GetRacesForSeason$raceResults$data.fromJson(json));
      });
      var qnr2 = raceResults
          .where((element) => element.attributes?.race?.data?.attributes?.type == MotoGpRaceUtils.MOTO_RACE_QUALI2)
          .toList();
      var qualis = qnr2 + qnr1ForQuali;

      var qualiPositions = qualis.map((race) => race.attributes?.position).where((pos) => pos != null).cast<int>();
      map[bestQualiPosKey] = qualiPositions.isNotEmpty ? qualiPositions.reduce((a, b) => a < b ? a : b) : 0;
      var sumOfQualiPositions = qualiPositions.fold(0.0, (sum, position) => sum + (position));
      map[avgQualiPosKey] = qualiPositions.isNotEmpty ? sumOfQualiPositions / qualis.length : -999;

      var qualisForGrid = qnr1 + qnr2;
      if (isSprint) {
        // take sprint final position first then final position and then normal position
        map[polesKey] = qualisForGrid
            .where((race) =>
                (race.attributes?.sprintFinalPos ?? race.attributes?.finalPos ?? race.attributes?.position) == 1)
            .length;
        map[firstRowStartsKey] = qualisForGrid
            .where((race) =>
                (race.attributes?.sprintFinalPos ?? race.attributes?.finalPos ?? race.attributes?.position) != null &&
                (race.attributes?.sprintFinalPos ?? race.attributes?.finalPos ?? race.attributes?.position)! <= 3)
            .length;
        map[q3AppearancesKey] = qnr2.length;
        var qualiGridPositions = qualisForGrid.map(
            (race) => race.attributes?.sprintFinalPos ?? race.attributes?.finalPos ?? race.attributes?.position ?? 0);
        var sumOfQualiGridPositions = qualiGridPositions.fold(0.0, (sum, position) => sum + (position));
        map[avgStartGridPosKey] = qualiGridPositions.isNotEmpty ? sumOfQualiGridPositions / qualisForGrid.length : -999;
        if (map[avgFinishPosKey] == -999) {
          map[avgPositionGainedKey] = -999;
        } else {
          map[avgPositionGainedKey] = map[avgStartGridPosKey] - map[avgFinishPosKey];
        }
      } else {
        map[polesKey] =
            qualisForGrid.where((race) => (race.attributes?.finalPos ?? race.attributes?.position) == 1).length;
        map[firstRowStartsKey] = qualisForGrid
            .where((race) =>
                (race.attributes?.finalPos ?? race.attributes?.position) != null &&
                (race.attributes?.finalPos ?? race.attributes?.position)! <= 3)
            .length;
        map[q3AppearancesKey] = qnr2.length;
        var qualiGridPositions =
            qualisForGrid.map((race) => race.attributes?.finalPos ?? race.attributes?.position ?? 0);
        var sumOfQualiGridPositions = qualiGridPositions.fold(0.0, (sum, position) => sum + (position));
        map[avgStartGridPosKey] = qualiGridPositions.isNotEmpty ? sumOfQualiGridPositions / qualisForGrid.length : -999;
        if (map[avgFinishPosKey] == -999) {
          map[avgPositionGainedKey] = -999;
        } else {
          map[avgPositionGainedKey] = map[avgStartGridPosKey] - map[avgFinishPosKey];
        }
      }
    }

    populateQualiData('racePoles', 'raceFirstRowStarts', 'q3Appearances', 'bestQualiPos', 'avgRaceQualiPosition',
        'avgRaceStartGridPosition', 'avgRacePositionGained', 'avgRaceFinishPosition', false);
    populateQualiData(
        'sprintPoles',
        'sprintFirstRowStarts',
        'sprintQ3Appearances',
        'bestSprintQualiPos',
        'avgSprintQualiPosition',
        'avgSprintStartGridPosition',
        'avgSprintPositionGained',
        'avgSprintFinishPosition',
        true);

    Set<String> uniqueGrandPrixIds = {};
    for (var result in raceResults) {
      if (result.attributes?.race?.data?.attributes?.grandPrix?.data?.id != null) {
        uniqueGrandPrixIds.add((result.attributes?.race?.data?.attributes?.grandPrix?.data?.id)!);
      }
    }
    map["noOfGPs"] = uniqueGrandPrixIds.length;
    map['standings_id'] = standingId;
    map['driver_season_grid_id'] = driverSeasonGridId;
    map['is_primary_grid_id'] = isPrimaryGridId;
    map[RaceResult.POSITION] = position;
    // todo avgRacePositionGained, avgSprintPositionGained, biggestRaceWinMargins
    return map;
  }

  Future<void> _updateConfig(String year) async {
    await strapiRepo.updateConfig(CommonUtils.MOTOGP_CLIENT, year, "");
  }
}
