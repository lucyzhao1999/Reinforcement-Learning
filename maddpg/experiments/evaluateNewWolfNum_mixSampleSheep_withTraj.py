import os
import sys
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
os.environ['KMP_DUPLICATE_LIB_OK']='True'
dirName = os.path.dirname(__file__)
sys.path.append(os.path.join(dirName, '..'))
sys.path.append(os.path.join(dirName, '..', '..'))
import logging
logging.getLogger('tensorflow').setLevel(logging.ERROR)

from environment.chasingEnv.multiAgentEnv import *
from functionTools.loadSaveModel import saveToPickle, restoreVariables, loadFromPickle
from functionTools.trajectory import SampleTrajectory
from environment.chasingEnv.multiAgentEnvWithIndividReward import RewardWolfIndividual

from maddpg.maddpgAlgor.trainer.myMADDPG import *
import pandas as pd
import matplotlib.pyplot as plt
from collections import OrderedDict
import random

wolfColor = np.array([0.85, 0.35, 0.35])
sheepColor = np.array([0.35, 0.85, 0.35])
blockColor = np.array([0.25, 0.25, 0.25])

# python3 evaluateNewWolfNum_mixSampleSheep_withTraj.py

def calcWolfTrajReward(traj, wolvesID):
    rewardIDinTraj = 2
    getWolfReward = lambda allAgentsReward: np.sum([allAgentsReward[wolfID] for wolfID in wolvesID])
    rewardList = [getWolfReward(timeStepInfo[rewardIDinTraj]) for timeStepInfo in traj]
    trajReward = np.sum(rewardList)
    return trajReward


class EvaluateWolfSheepTrain:
    def __init__(self, getSheepModelPaths):
        self.getSheepModelPaths = getSheepModelPaths
        self.getSampledSheepPath = lambda sheepPaths: sheepPaths[random.randint(0, len(sheepPaths) - 1)]

    def __call__(self, df):
        numWolves = df.index.get_level_values('numWolves')[0]
        sheepSpeedMultiplier = df.index.get_level_values('sheepSpeedMultiplier')[0]# [1, 1.25]
        wolfIndividual = df.index.get_level_values('wolfIndividual')[0] #[shared, individ]
        costActionRatio = df.index.get_level_values('costActionRatio')[0]# [0.01, 0.05, 0.1]

        numSheeps = 1
        numBlocks = 2
        maxTimeStep = 75
        maxEpisode = 60000
        collisionReward = 30
        maxRunningStepsToSample = 75

        numAgents = numWolves + numSheeps
        numEntities = numAgents + numBlocks
        wolvesID = list(range(numWolves))
        sheepsID = list(range(numWolves, numAgents))
        blocksID = list(range(numAgents, numEntities))

        wolfSize = 0.075
        sheepSize = 0.05
        blockSize = 0.2
        entitiesSizeList = [wolfSize] * numWolves + [sheepSize] * numSheeps + [blockSize] * numBlocks

        folderName = 'maddpgWolfNum_WolfReward_ActionCost_SheepSpeed'
        trajectoryDirectory = os.path.join(dirName, '..', 'trajectories', folderName)
        trajFileName = "maddpg{}wolves{}sheep{}blocks{}episodes{}stepSheepSpeed{}WolfActCost{}{}_mixTraj".format(
            numWolves, numSheeps, numBlocks, maxEpisode, maxTimeStep, sheepSpeedMultiplier, costActionRatio, wolfIndividual)
        trajSavePath = os.path.join(trajectoryDirectory, trajFileName)
        trajList= loadFromPickle(trajSavePath)

        reshapeAction = ReshapeAction()
        getActionCost = GetActionCost(costActionRatio, reshapeAction, individualCost=True)
        getWolvesAction = lambda action: [action[wolfID] for wolfID in wolvesID]

        isCollision = IsCollision(getPosFromAgentState)
        individ = True if wolfIndividual == 'individ' else False
        rewardWolf = RewardWolf(wolvesID, sheepsID, entitiesSizeList, isCollision, collisionReward, individ)

        rewardList = []
        biteList = []
        actionMagnSumList = []
        actionCostList = []

        for traj in trajList: # SARS'
            epsReward = 0
            epsBite = 0
            epsActionSum = 0
            epsActionCost = 0

            for timeStepInfo in traj:
                state = timeStepInfo[0]
                action = timeStepInfo[1]
                nextState = timeStepInfo[3]

                actionCost = np.array(getActionCost(getWolvesAction(action)))
                actionCostTot = np.sum(actionCost)

                wolvesActions = [reshapeAction(action[wolfID]) for wolfID in wolvesID]
                actionMagnitudeTot = np.sum([np.linalg.norm(np.array(agentAction), ord=2) for agentAction in wolvesActions])

                wolvesReward = rewardWolf(state, action, nextState)
                reward = np.sum(wolvesReward)
                bite = reward/ collisionReward

                epsReward += reward
                epsBite += bite
                epsActionSum += actionMagnitudeTot
                epsActionCost += actionCostTot

            actionMagnSumList.append(epsActionSum)
            rewardList.append(epsReward)
            biteList.append(epsBite)
            actionCostList.append(epsActionCost)

        meanTrajReward = np.mean(rewardList)
        seTrajReward = np.std(rewardList) / np.sqrt(len(rewardList) - 1)
        print('meanTrajReward', meanTrajReward, 'se ', seTrajReward)

        meanTrajBite = np.mean(biteList)
        seTrajBite = np.std(biteList) / np.sqrt(len(biteList) - 1)
        print('meanTrajBite', meanTrajBite, 'se ', seTrajBite)

        meanTrajActionMagnitudeSum = np.mean(actionMagnSumList)
        seTrajAction = np.std(actionMagnSumList) / np.sqrt(len(actionMagnSumList) - 1)
        print('meanTrajActionMagnitude', meanTrajActionMagnitudeSum, 'se ', seTrajAction)

        meanTrajActionCost = np.mean(actionCostList)
        seTrajActionCost = np.std(actionCostList) / np.sqrt(len(actionCostList) - 1)
        print('meanTrajActionCost', meanTrajActionCost, 'se ', seTrajActionCost)

        return pd.Series({'meanReward': meanTrajReward, 'seReward': seTrajReward, 'meanBite': meanTrajBite, 'seBite': seTrajBite,
                          'meanTrajActionMagnitude': meanTrajActionMagnitudeSum, 'seAction': seTrajAction, 'meanActionCost': meanTrajActionCost, 'seActionCost': seTrajActionCost})


class GetSheepModelPaths:
    def __init__(self, sheepSpeedList, costActionRatioList, wolfTypeList):
        self.sheepSpeedList = sheepSpeedList
        self.wolfTypeList = wolfTypeList
        self.costActionRatioList = costActionRatioList

    def __call__(self, numWolves, numSheeps, numBlocks, maxEpisode, maxTimeStep):
        dirName = os.path.dirname(__file__)
        fileNameList = ["maddpg{}wolves{}sheep{}blocks{}episodes{}stepSheepSpeed{}WolfActCost{}{}_agent{}".format(
            numWolves, numSheeps, numBlocks, maxEpisode, maxTimeStep, sheepSpeedMultiplier, costActionRatio, wolfIndividual, numWolves)
            for sheepSpeedMultiplier in self.sheepSpeedList for wolfIndividual in self.wolfTypeList for costActionRatio in self.costActionRatioList]
        folderName = 'maddpgWolfNum_WolfReward_ActionCost_SheepSpeed'
        sheepPaths = [os.path.join(dirName, '..', 'trainedModels', folderName, fileName) for fileName in fileNameList]

        return sheepPaths


def main():
    independentVariables = OrderedDict()
    independentVariables['wolfIndividual'] = ['shared', 'individ']
    independentVariables['numWolves'] = [2, 3, 4, 5, 6]
    independentVariables['sheepSpeedMultiplier'] = [1.0, 1.25]
    independentVariables['costActionRatio'] = [0, 0.05, 0.1]

    getSheepModelPaths = GetSheepModelPaths(independentVariables['sheepSpeedMultiplier'], independentVariables['costActionRatio'], independentVariables['wolfIndividual'])
    evaluateWolfSheepTrain = EvaluateWolfSheepTrain(getSheepModelPaths)

    levelNames = list(independentVariables.keys())
    levelValues = list(independentVariables.values())
    levelIndex = pd.MultiIndex.from_product(levelValues, names=levelNames)
    toSplitFrame = pd.DataFrame(index=levelIndex)
    # resultDF = toSplitFrame.groupby(levelNames).apply(evaluateWolfSheepTrain)

    resultPath = os.path.join(dirName, '..', 'evalResults')
    resultLoc = os.path.join(resultPath, 'newEvalWolfNum_actCost_speed_fullInfo.pkl')

    # saveToPickle(resultDF, resultLoc)

    resultDF = loadFromPickle(resultLoc)
    print(resultDF.to_string())
    # with pd.option_context('display.max_rows', None, 'display.max_columns', None):
    #     print(resultDF)
    # figure = plt.figure(figsize=(11, 7))
    # plotCounter = 1
    #
    # numRows = len(independentVariables['sheepSpeedMultiplier'])
    # numColumns = len(independentVariables['costActionRatio'])
    #
    # for key, outmostSubDf in resultDF.groupby('sheepSpeedMultiplier'):
    #     outmostSubDf.index = outmostSubDf.index.droplevel('sheepSpeedMultiplier')
    #     for keyCol, outterSubDf in outmostSubDf.groupby('costActionRatio'):
    #         outterSubDf.index = outterSubDf.index.droplevel('costActionRatio')
    #         axForDraw = figure.add_subplot(numRows, numColumns, plotCounter)
    #         for keyRow, innerSubDf in outterSubDf.groupby('wolfIndividual'):
    #             innerSubDf.index = innerSubDf.index.droplevel('wolfIndividual')
    #             plt.ylim([0, 2000])
    #
    #             innerSubDf.plot.line(ax = axForDraw, y='meanTrajActionMagnitude', yerr='seAction', label = keyRow, uplims=True, lolims=True, capsize=3)
    #             if plotCounter <= numColumns:
    #                 axForDraw.title.set_text('actionCost/actionMagnitude = ' + str(keyCol))
    #             if plotCounter% numColumns == 1:
    #                 axForDraw.set_ylabel('sheepSpeed' + str(key) + 'x')
    #             axForDraw.set_xlabel('Number of Wolves')
    #
    #         plotCounter += 1
    #         axForDraw.set_aspect(0.002, adjustable='box')
    #         plt.xticks(independentVariables['numWolves'])
    #
    #         plt.legend(title='Wolf type')
    #
    # figure.text(x=0.03, y=0.5, s='Average Wolves Moving Distance Per Episode', ha='center', va='center', rotation=90)
    # plt.suptitle('MADDPG Evaluate wolfType/ sheepSpeed/ actionCost')
    # plt.savefig(os.path.join(resultPath, 'newEvalWolfNum_actCost_speed_fullInfo_actionMagnitude'))
    # plt.show()

    # figure = plt.figure(figsize=(8, 8))
    # plotCounter = 1
    #
    # numRows = len(independentVariables['sheepSpeedMultiplier'])
    # numColumns = len(independentVariables['wolfIndividual'])
    #
    # for key, outmostSubDf in resultDF.groupby('sheepSpeedMultiplier'):
    #     outmostSubDf.index = outmostSubDf.index.droplevel('sheepSpeedMultiplier')
    #     for keyCol, outterSubDf in outmostSubDf.groupby('wolfIndividual'):
    #         outterSubDf.index = outterSubDf.index.droplevel('wolfIndividual')
    #         axForDraw = figure.add_subplot(numRows, numColumns, plotCounter)
    #         for keyRow, innerSubDf in outterSubDf.groupby('costActionRatio'):
    #             innerSubDf.index = innerSubDf.index.droplevel('costActionRatio')
    #             plt.ylim([0, 2000])
    #
    #             innerSubDf.plot.line(ax = axForDraw, y='meanTrajActionMagnitude', yerr='seAction', label = keyRow, uplims=True, lolims=True, capsize=3)
    #             if plotCounter <= numColumns:
    #                 axForDraw.title.set_text('Wolf type = ' + str(keyCol))
    #             if plotCounter% numColumns == 1:
    #                 axForDraw.set_ylabel('sheepSpeed' + str(key) + 'x')
    #             axForDraw.set_xlabel('Number of Wolves')
    #
    #         plotCounter += 1
    #         axForDraw.set_aspect(0.002, adjustable='box')
    #         plt.xticks(independentVariables['numWolves'])
    #
    #         plt.legend(title='costActionRatio')
    #
    # figure.text(x=0.03, y=0.5, s='Average Wolves Moving Distance Per Episode', ha='center', va='center', rotation=90)
    # plt.suptitle('MADDPG Evaluate wolfType/ sheepSpeed/ actionCost')
    # plt.savefig(os.path.join(resultPath, 'newEvalWolfNum_actCost_speed_fullInfo_actionMagnitude_groupByIndivid'))
    # plt.show()


    figure = plt.figure(figsize=(11, 7))
    plotCounter = 1
    numRows = len(independentVariables['sheepSpeedMultiplier'])
    numColumns = len(independentVariables['costActionRatio'])

    for key, outmostSubDf in resultDF.groupby('sheepSpeedMultiplier'):
        outmostSubDf.index = outmostSubDf.index.droplevel('sheepSpeedMultiplier')
        for keyCol, outterSubDf in outmostSubDf.groupby('costActionRatio'):
            outterSubDf.index = outterSubDf.index.droplevel('costActionRatio')
            axForDraw = figure.add_subplot(numRows, numColumns, plotCounter)
            for keyRow, innerSubDf in outterSubDf.groupby('wolfIndividual'):
                innerSubDf.index = innerSubDf.index.droplevel('wolfIndividual')
                plt.ylim([0, 1500])

                innerSubDf.plot.line(ax = axForDraw, y='meanReward', yerr='seReward', label = keyRow, uplims=True, lolims=True, capsize=3)
                if plotCounter <= numColumns:
                    axForDraw.title.set_text('actionCost/actionMagnitude = ' + str(keyCol))
                if plotCounter% numColumns == 1:
                    axForDraw.set_ylabel('sheepSpeed' + str(key) + 'x')
                axForDraw.set_xlabel('Number of Wolves')

            plotCounter += 1
            axForDraw.set_aspect(0.0025, adjustable='box')
            plt.xticks(independentVariables['numWolves'])

            plt.legend(title='Wolf type')

    figure.text(x=0.03, y=0.5, s='Mean Episode Reward Without Action Cost', ha='center', va='center', rotation=90)
    plt.suptitle('MADDPG Evaluate wolfType/ sheepSpeed/ actionCost')
    plt.savefig(os.path.join(resultPath, 'newEvalWolfNum_actCost_speed_fullInfo_trajRewardNoCost'))
    plt.show()

if __name__ == '__main__':
    main()
